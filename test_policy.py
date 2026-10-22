"""Consumer-visible safety boundaries for the shared unsubscribe policy."""

import json
import math
import unittest

from policy import (
    POLITICAL_MIN,
    POLITICAL_SCORE_PATTERN,
    TRANSACTIONAL_MAX,
    TRANSACTIONAL_SCORE_PATTERN,
    decision_from_response,
    local_decision,
    normalize_phone,
    opt_out_keyword,
    score_text_meets,
)


class PhonePolicyTests(unittest.TestCase):
    def test_formats_share_canonical_number(self):
        for value in ("+1 (212) 555-0100", "212.555.0100", "(212) 555 0100"):
            with self.subTest(value=value):
                self.assertEqual(normalize_phone(value), "2125550100")

    def test_digit_count_is_checked_before_truncation(self):
        cases = (
            ("1234", None),
            ("12345", "12345"),
            ("123456789012345", "6789012345"),
            ("1234567890123456", None),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(normalize_phone(value), expected)

    def test_sender_must_be_one_ascii_phone_string(self):
        for value in (
            "someone@example.com",
            "Jane Smith",
            "Jane <2125550100>",
            "12345,67890",
            "12345;67890",
            "12345/67890",
            "+12345 +67890",
            "12345\n",
            "12345\t",
            "１２３４５",
            "١٢٣٤٥",
            "12345 ext. 9",
            ["12345", "67890"],
            None,
            "",
            "+(). -",
        ):
            with self.subTest(value=value):
                self.assertIsNone(normalize_phone(value))

    def test_extension_is_removed_only_from_contacts(self):
        for suffix in (",123", ";123", " ext 123", " EXT. 123", "x123", " x 123"):
            value = "+1 (212) 555-0100" + suffix
            with self.subTest(suffix=suffix):
                self.assertEqual(normalize_phone(value, contact=True), "2125550100")
                self.assertIsNone(normalize_phone(value))
        self.assertIsNone(normalize_phone("2125550100 ext.", contact=True))

    def test_short_codes_remain_distinct_from_long_numbers(self):
        # 555-0100..0199 numbers are reserved as fictional; the long number ends in the short code.
        body = "Vote for Jane. Reply STOP to opt out."
        self.assertEqual(local_decision("50145", body, ["+1 212 555 0145"]), ("eligible", "STOP"))
        self.assertEqual(local_decision("50145", body, ["50145"]), ("contact", None))

    def test_canonical_collisions_skip_conservatively(self):
        body = "Vote for Jane. Reply STOP to opt out."
        self.assertEqual(
            local_decision("+44 212 555 0100", body, ["+1 (212) 555-0100 x999"]),
            ("contact", None),
        )


class OptOutPolicyTests(unittest.TestCase):
    def test_each_recognized_reply_can_be_used(self):
        for keyword in ("STOP", "END", "QUIT", "CANCEL", "UNSUBSCRIBE"):
            with self.subTest(keyword=keyword):
                self.assertEqual(
                    opt_out_keyword(f"Vote Jane. Reply {keyword.lower()} to opt out."),
                    keyword,
                )

    def test_quoted_keywords_and_command_variants(self):
        cases = (
            ("Text 'STOP' to unsubscribe.", "STOP"),
            ('Respond with "END" to stop messages.', "END"),
            ("Send \u201cQUIT\u201d to end texts.", "QUIT"),
            ("Reply \u2018CANCEL\u2019 to be removed from our list.", "CANCEL"),
            ("To unsubscribe, reply UNSUBSCRIBE.", "UNSUBSCRIBE"),
            ("Reply STOP", "STOP"),
            ("Reply STOP to stop.", "STOP"),
        )
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(opt_out_keyword(body), expected)

    def test_instruction_is_found_before_last_paragraph(self):
        body = "Vote for Jane.\nReply END to unsubscribe.\nPaid for by Jane's campaign."
        self.assertEqual(opt_out_keyword(body), "END")
        self.assertEqual(opt_out_keyword("Reply STOP\nVote for Jane."), "STOP")

    def test_terse_opt_out_instructions(self):
        cases = (
            ("Vote for Jane.\nStop to End", "STOP"),
            ("Vote for Jane. stop2end", "STOP"),
            ("Vote for Jane. STOPTOOPTOUT", "STOP"),
            ("Vote for Jane. END2END", "END"),
            ("Vote for Jane. END to end.", "END"),
            ("STOP to quit.\n" + "Election campaign footer. " * 8, "STOP"),
        )
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(opt_out_keyword(body), expected)

    def test_original_shortcut_phrase_list(self):
        """Every phrase the original Auto Unsubscribe handled maps to one reply keyword."""
        cases = {
            "stoptoend": "STOP", "stoptoquit": "STOP", "stoptooptout": "STOP", "stoptostop": "STOP",
            "stop2end": "STOP", "STOP2END": "STOP", "Stop To End": "STOP", "Text STOP 2 END": "STOP",
            "Reply STOP to END": "STOP", "endtoend": "END", "end2end": "END", "END2END": "END",
            "END2STOP": "END", "Reply END to quit": "END",
            # Compound tokens inside reply commands (seen on device): reply the first keyword.
            "Reply END2END to opt out.": "END", "Reply STOP2END to opt out.": "STOP",
            "Text STOPTOEND to unsubscribe.": "STOP", "Reply 'END2END' to opt out.": "END",
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(opt_out_keyword(f"Vote for our candidate. {phrase}"), expected)

    def test_ordinary_words_and_non_opt_out_commands_do_not_qualify(self):
        for body in (
            "Vote to stop corruption and end waste.",
            "Our END2END campaign needs your vote.",
            "Reply STOPPING to opt out.",
            "Reply STOP_NOW to opt out.",
            "Reply to stop corruption.",
            "Reply STOP to stop corruption.",
            "Reply END to end the opposition.",
            "Reply CANCEL to cancel their campaign.",
            "Reply YES to vote.",
            "Please unsubscribe if you dislike politics.",
            'The phrase "STOP" appears in our campaign slogan.',
            'The slogan "Reply STOP" is not an opt-out instruction.',
        ):
            with self.subTest(body=body):
                self.assertIsNone(opt_out_keyword(body))

    def test_negated_commands_are_not_opt_out_instructions(self):
        for body in (
            "Vote Jane. Do not reply STOP.",
            "Vote Jane. Don't text END to unsubscribe.",
            "Vote Jane. Never send QUIT.",
            "Vote Jane. Do not STOP to end.",
            "Vote Jane. Do not\nreply STOP.",
            "Reply STOP to opt out. Do not reply STOP.",
        ):
            with self.subTest(body=body):
                self.assertIsNone(opt_out_keyword(body))

    def test_repeated_same_keyword_is_not_a_conflict(self):
        self.assertEqual(
            opt_out_keyword("Reply STOP to opt out. More info. Text 'STOP' to unsubscribe."),
            "STOP",
        )
        self.assertEqual(opt_out_keyword("Reply STOP or STOP to opt out."), "STOP")

    def test_distinct_commands_anywhere_are_a_conflict(self):
        for body in (
            "Reply STOP to opt out.\nText END to unsubscribe.",
            "Reply STOP or END to opt out.",
            "Reply 'STOP', 'END' or 'QUIT' to unsubscribe.",
            "Reply STOP/END to opt out.",
            "Reply STOP and CANCEL to opt out.",
        ):
            with self.subTest(body=body):
                self.assertIsNone(opt_out_keyword(body))


class LocalGateTests(unittest.TestCase):
    def test_local_medical_veto_overrides_political_words(self):
        for body in (
            "Dr. Vote reminds you to come tomorrow. Reply STOP to opt out.",
            "Senator Smith: your clinic appointment is tomorrow. Reply STOP.",
            "Vote Medical: your test results are ready. Reply END to unsubscribe.",
            "Your prescription is ready on Election Street. Reply STOP.",
        ):
            with self.subTest(body=body):
                self.assertEqual(local_decision("12345", body, []), ("transactional", None))

    def test_candidate_identity_does_not_override_appointment_reminder(self):
        self.assertEqual(
            local_decision("12345", "Candidate Jane: appointment tomorrow at noon. Reply STOP.", []),
            ("transactional", None),
        )
        self.assertEqual(
            local_decision("12345", "The president appointed Jane. Vote for our candidate. Reply STOP.", []),
            ("eligible", "STOP"),
        )
        self.assertEqual(
            local_decision("12345", "Vote against the president's cabinet appointments. Reply STOP.", []),
            ("transactional", None),
        )

    def test_other_transactional_purposes_are_local_vetoes(self):
        for body in (
            "Campaign account verification code: 123456. Reply STOP.",
            "Election merchandise order delivery tomorrow. Reply STOP.",
            "Candidate fundraiser payment receipt enclosed. Reply STOP.",
            "Political conference booking confirmed. Reply STOP.",
        ):
            with self.subTest(body=body):
                self.assertEqual(local_decision("12345", body, []), ("transactional", None))

    def test_both_political_and_unambiguous_opt_out_are_required(self):
        cases = (
            ("Shop our sale. Reply STOP to unsubscribe.", ("not_political", None)),
            ("Vote for Jane to stop corruption.", ("no_opt_out", None)),
            ("Vote Jane. Reply STOP or END to unsubscribe.", ("no_opt_out", None)),
            ("Vote Jane. Reply STOP to unsubscribe.", ("eligible", "STOP")),
        )
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(local_decision("12345", body, []), expected)


class JevDecisionTests(unittest.TestCase):
    @staticmethod
    def response(political=1, transactional=0):
        return {
            "answers": {
                "political_outreach": {"type": "noul", "noul": political},
                "transactional": {"type": "noul", "noul": transactional},
            }
        }

    def test_both_thresholds_are_inclusive_and_required(self):
        cases = (
            (1, 0, True),
            (0.95, 0.05, True),
            (math.nextafter(0.95, 0), 0, False),
            (1, math.nextafter(0.05, 1), False),
            (0, 0, False),
            (1, 1, False),
        )
        for political, transactional, expected in cases:
            with self.subTest(political=political, transactional=transactional):
                self.assertIs(decision_from_response(self.response(political, transactional)), expected)

    def test_score_text_thresholds_match_numeric_thresholds(self):
        """The shortcut compares JSON number text; it must never exceed the numeric policy."""
        values = [i / 10000 for i in range(10001)] + [
            math.nextafter(POLITICAL_MIN, 0), math.nextafter(TRANSACTIONAL_MAX, 1),
            1e-5, 3.2e-7, 4.99e-2, 5e-2, 5.01e-2, 9.99e-3, 0.0499999, 0.0500001, 0.9499999, 0.9500001,
        ]
        texts = {json.dumps(value) for value in values}
        texts |= {"0", "1", "1.0", "1e0", "0.0", "5e-2", "5.0E-2", "4.9e-2", "9.5e-1", "9.49e-1",
                  "1e-3", "9.99e-3", "1.5e-2", "1e-2", "5.1e-2", "1.01", "-0.0", "2", "1e1"}
        for text in sorted(texts):
            value = float(text)
            with self.subTest(score=text):
                if score_text_meets(text, POLITICAL_SCORE_PATTERN):
                    self.assertGreaterEqual(value, POLITICAL_MIN)
                    self.assertLessEqual(value, 1)
                if score_text_meets(text, TRANSACTIONAL_SCORE_PATTERN):
                    self.assertGreaterEqual(value, 0)
                    self.assertLessEqual(value, TRANSACTIONAL_MAX)
        # Every standard JSON serialization inside a threshold is recognized.
        for value in values:
            text = json.dumps(value)
            with self.subTest(serialized=text):
                self.assertEqual(score_text_meets(text, POLITICAL_SCORE_PATTERN), POLITICAL_MIN <= value <= 1)
                self.assertEqual(score_text_meets(text, TRANSACTIONAL_SCORE_PATTERN), 0 <= value <= TRANSACTIONAL_MAX)

    def test_invalid_numeric_values_are_rejected_in_either_answer(self):
        for value in (True, False, "1", "0", "0.95", None, [], {}, float("nan"),
                      float("inf"), float("-inf"), -0.01, 1.01, 10 ** 500):
            for name in ("political_outreach", "transactional"):
                response = self.response()
                response["answers"][name]["noul"] = value
                with self.subTest(name=name, value=value):
                    self.assertFalse(decision_from_response(response))

    def test_missing_or_wrong_answer_shape_is_rejected(self):
        for answer in (None, [], 1, "1", {}, {"noul": 1}, {"type": "noul"},
                       {"type": "boolean", "noul": 1}, {"type": "NOUL", "noul": 1}):
            for name in ("political_outreach", "transactional"):
                response = self.response()
                response["answers"][name] = answer
                with self.subTest(name=name, answer=answer):
                    self.assertFalse(decision_from_response(response))
        response = self.response()
        response["answers"]["political_outreach"] = {"type": "noul", "noul": True, "nested": {"noul": 1}}
        self.assertFalse(decision_from_response(response))
        for name in ("political_outreach", "transactional"):
            response = self.response()
            del response["answers"][name]
            with self.subTest(missing=name):
                self.assertFalse(decision_from_response(response))

    def test_malformed_outer_responses_are_rejected(self):
        for response in (None, [], "{}", 1, True, {}, {"answers": None},
                         {"answers": []}, {"answers": "not JSON"}):
            with self.subTest(response=response):
                self.assertFalse(decision_from_response(response))

    def test_error_envelopes_cannot_be_overridden_by_answers(self):
        for key, value in (("error", {"code": 429, "message": "rate limited"}),
                           ("error", "failed"), ("error", None),
                           ("errors", [{"message": "failed"}])):
            response = self.response()
            response[key] = value
            with self.subTest(key=key, value=value):
                self.assertFalse(decision_from_response(response))


if __name__ == "__main__":
    unittest.main()
