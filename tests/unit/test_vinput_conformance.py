"""Run the vinput replay contract across the interpreter and both build targets."""
import test_hid_conformance as hid_vectors


class VinputConformance(hid_vectors.HidConformance):
    vectors = hid_vectors.ROOT / "tests/conformance/vinput"
    probe = vectors / "probe.lm"
    effects = (*hid_vectors.EFFECTS, "vinput.emit")
    extensions = ("hid", "vinput")

    def assert_log(self, actual, vector):
        super().assert_log(actual, vector)
        if vector["probe"] in ("implicit", "fault", "interrupt"):
            self.assertGreaterEqual(actual[2]["at-ms"], 25)
