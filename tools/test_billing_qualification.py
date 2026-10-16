"""Synthetic local qualification records; these fixtures are not provider evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import billing_qualification as bq

MODELS = {"cloud-S": "claude-sonnet-5-5", "cloud-C": "claude-haiku-5-5",
          "cloud-O": "claude-opus-5-5", "cloud-F": "claude-fable-5-1"}
PRICE_MODELS = {"cloud-S": "Claude Sonnet 5.5", "cloud-C": "Claude Haiku 5.5",
                "cloud-O": "Claude Opus 5.5", "cloud-F": "Claude Fable 5.1"}
ENDPOINT = "https://api.anthropic.com"


def synthetic_fixture(directory):
    """Write conspicuously synthetic artifacts only under a disposable folder."""
    root = Path(directory)
    price_path, record_path = root / "synthetic-prices.json", root / "synthetic-qualification.json"
    price_bytes = Path(__file__).with_name("prices-2.json").read_bytes()
    price_path.write_bytes(price_bytes)
    refs = []
    for kind in sorted(bq.EVIDENCE_KINDS):
        artifact = root / (kind + ".txt")
        body = ("SYNTHETIC TEST ONLY: no provider qualification or real ceiling established. " + kind).encode()
        artifact.write_bytes(body)
        refs.append({"kind": kind, "path": artifact.name, "sha256": hashlib.sha256(body).hexdigest()})
    record = {"schema_version": 1, "qualified": True,
              "qualification_scope": bq.QUALIFICATION_SCOPE, "final_bill_guaranteed": False,
              "endpoint": ENDPOINT, "request_mode": bq.REQUEST_MODE,
              "price_revision": json.loads(price_bytes)["revision"],
              "price_sha256": hashlib.sha256(price_bytes).hexdigest(),
              "verified_at": 1000, "expires_at": 2000, "evidence_refs": refs,
              "note": "SYNTHETIC TEST ONLY, never use for live dispatch", "profiles": {}}
    for profile, model in MODELS.items():
        record["profiles"][profile] = {"model_id": model, "price_model": PRICE_MODELS[profile],
            "input_token_ceiling": 10000, "max_output_tokens": 4096,
            "bound_kind": "provider-enforced-token-ceiling", "evidence_refs": deepcopy(refs)}
    record_path.write_text(json.dumps(record), encoding="utf-8")
    return record_path, price_path, record


class BillingQualification(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.record_path, self.price_path, self.record = synthetic_fixture(self.temp.name)

    def load(self, now=1500):
        return bq.load_qualification(self.record_path, self.price_path,
            endpoint=ENDPOINT, models=MODELS, price_models=PRICE_MODELS, now=now)

    def save(self, record):
        self.record_path.write_text(json.dumps(record), encoding="utf-8")

    def test_fresh_matching_synthetic_record(self):
        self.assertEqual(self.load(), self.record)
        self.assertFalse(self.load()["final_bill_guaranteed"])

    def test_default_record_remains_unqualified(self):
        with self.assertRaises(bq.BillingQualificationError):
            bq.load_qualification(Path(__file__).with_name("live_billing_qualification.json"),
                self.price_path, endpoint=ENDPOINT, models=MODELS, price_models=PRICE_MODELS)

    def test_configuration_and_scope_mismatches_refused(self):
        for field, value in (("qualified", False), ("qualified", 1), ("schema_version", True),
                             ("endpoint", "https://foreign.invalid"), ("request_mode", "tools"),
                             ("qualification_scope", "final-bill"), ("final_bill_guaranteed", True),
                             ("price_revision", "different"), ("price_sha256", "0" * 64)):
            with self.subTest(field=field, value=value):
                self.save(dict(self.record, **{field: value}))
                with self.assertRaises(bq.BillingQualificationError): self.load()

    def test_expiry_future_and_nonfinite_times_refused(self):
        for now in (999, 2000, float("nan"), float("inf"), True, -1):
            with self.subTest(now=now), self.assertRaises(bq.BillingQualificationError): self.load(now)
        for field in ("verified_at", "expires_at"):
            self.save(dict(self.record, **{field: None}))
            with self.assertRaises(bq.BillingQualificationError): self.load()

    def test_changed_price_bytes_refused(self):
        self.price_path.write_bytes(self.price_path.read_bytes() + b" ")
        with self.assertRaises(bq.BillingQualificationError): self.load()

    def test_artifact_integrity_presence_and_scope_required(self):
        ref = self.record["evidence_refs"][0]
        artifact = self.record_path.parent / ref["path"]
        artifact.write_text("changed private capture", encoding="utf-8")
        with self.assertRaises(bq.BillingQualificationError) as error: self.load()
        self.assertNotIn("private capture", str(error.exception))
        artifact.unlink()
        with self.assertRaises(bq.BillingQualificationError): self.load()

    def test_invalid_evidence_and_paths_fail_closed(self):
        for refs in ([], ["fixture://not-a-capture"], [{"kind": []}],
                     [dict(self.record["evidence_refs"][0], path="../outside.txt")],
                     [dict(self.record["evidence_refs"][0], path="https://example.invalid/data")],
                     self.record["evidence_refs"][:1]):
            self.save(dict(self.record, evidence_refs=refs))
            with self.assertRaises(bq.BillingQualificationError): self.load()

    def test_profile_identity_ceiling_and_evidence_required(self):
        for field, value in (("model_id", "different"), ("price_model", "different"),
                             ("input_token_ceiling", 0), ("input_token_ceiling", True),
                             ("max_output_tokens", 1.5), ("bound_kind", "estimate"),
                             ("evidence_refs", [])):
            record = deepcopy(self.record); record["profiles"]["cloud-C"][field] = value
            self.save(record)
            with self.subTest(field=field), self.assertRaises(bq.BillingQualificationError): self.load()

    def test_arbitrary_record_shapes_refused(self):
        for record in (None, [], {}, True, {"qualified": True, "schema_version": []}):
            self.save(record)
            with self.assertRaises(bq.BillingQualificationError): self.load()


if __name__ == "__main__":
    unittest.main(verbosity=2)
