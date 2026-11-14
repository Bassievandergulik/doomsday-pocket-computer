"""Symptom checker tests:  python3 -m unittest discover tests"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from symptoms import SymptomChecker  # noqa: E402

PATH = os.path.join(ROOT, "app", "symptoms.txt")


class SymptomTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = SymptomChecker(PATH)

    def top(self, q, n=1):
        r = self.c.check(q)
        return [x["id"] for x in r["conditions"][:n]] if r else []

    def test_table_is_complete(self):
        for sid, s in self.c.symptoms.items():
            for lang in ("en", "nl", "es"):
                self.assertTrue(s["words"].get(lang), "%s has no %s words" % (sid, lang))
        for c in self.c.conditions:
            self.assertIn(c["level"], ("now", "soon", "self"))
            self.assertTrue(c["advice"] and c["wiki"])
            if c["guide"]:
                self.assertTrue(os.path.exists(os.path.join(ROOT, "library", c["guide"] + ".md")), c["guide"])

    def test_same_answer_in_three_languages(self):
        for q in ("fever headache stiff neck", "koorts hoofdpijn stijve nek", "fiebre dolor de cabeza rigidez de nuca"):
            r = self.c.check(q)
            self.assertEqual(r["conditions"][0]["id"], "meningitis", q)
            self.assertTrue(r["danger"] and r["urgent"])
        self.assertEqual(self.c.check("koorts hoofdpijn stijve nek")["language"], "nl")
        self.assertEqual(self.c.check("koorts hoofdpijn stijve nek")["conditions"][0]["local"], "Hersenvliesontsteking")

    def test_common_descriptions(self):
        cases = {
            "pain in my chest and left arm, sweating": "heartattack",
            "diarrhea vomiting": "gastro",
            "diarree en overgeven": "gastro",
            "ik heb buikpijn rechtsonder en koorts": "appendicitis",
            "runny nose sore throat": "cold",
            "hoofpijn misselijk lichtschuw": "migraine",   # typo in hoofdpijn
            "headache dizzy nausea, gas heater": "co",
            "cough with green phlegm and fever": "pneumonia",
            "can't breathe, swollen lips after bee sting": "anaphylaxis",
            "drank river water, diarrhea and bloated": "giardia",
            "sweating confused shaky diabetic": "hypoglycaemia",
            "tired bleeding gums no fruit": "scurvy",
            "cara torcida habla arrastrada": "stroke",
            "burning when peeing": "uti",
        }
        for q, want in cases.items():
            self.assertEqual(self.top(q), [want], q)

    def test_context_alone_is_not_a_symptom_check(self):
        for q in ("water", "burn", "Utrecht", "river water", "mushrooms", "knots"):
            self.assertIsNone(self.c.check(q), q)

    def test_missing_circumstance_lowers_rank(self):
        # vomiting + diarrhoea is not mushroom poisoning unless you mention eating mushrooms
        self.assertNotIn("plantpoison", self.top("diarrhea vomiting", 2))
        self.assertEqual(self.top("vomiting diarrhea after eating wild mushrooms"), ["plantpoison"])

    def test_tells_what_else_to_check(self):
        c = self.c.check("fever headache stiff neck")["conditions"][0]
        self.assertIn("rash does not fade", c["also"])


if __name__ == "__main__":
    unittest.main()
