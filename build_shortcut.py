"""Build the native Auto Unsubscribe shortcut. Python is a build-time dependency only.

One shortcut does everything. It is delivered in stages so each step can be verified
on the phone before the next one adds more capability:

  1  Local filtering only. No network, no Send Message action.
  2  Adds the OpenRouter Jev decision. Still never sends.
  3  Adds the opt-out reply, guarded by a Dry run setting.

Manual runs (no Shortcut Input) ask for a test message and never send in any stage.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
import plistlib
from uuid import NAMESPACE_URL, uuid5

import policy

NAME = "Auto Unsubscribe - Jev"
TEST_SENDER = "+12025550199"
TEST_SAMPLE = (
    "Paid for by Friends of Candidate. Donate to our election campaign and vote "
    "this November. Reply STOP to opt out."
)
# Message automations embedded in the shortcut, in the format iOS exports
# (copied from the original Auto Unsubscribe). "end" also covers "end2end".
TRIGGER_PHRASES = ("stop", "end")
# Shortcuts If condition codes: 4 is, 5 is not, 100 has any value,
# 101 does not have any value (999 would mean "does not contain"). Numeric Ifs
# are only used on native Number outputs; scores are compared as text.
IS, IS_NOT, CONTAINS, HAS_VALUE, NO_VALUE = 4, 5, 99, 100, 101
KEYWORDS_PREFIX = "matched:"


def attachment(value):
    return {"WFSerializationType": "WFTextTokenAttachment", "Value": value}


def variable(name):
    return attachment({"Type": "Variable", "VariableName": name})


def shortcut_input(property_name=None):
    value = {"Type": "ExtensionInput"}
    if property_name:
        value["Aggrandizements"] = [{
            "Type": "WFPropertyVariableAggrandizement",
            "PropertyName": property_name,
        }]
    return attachment(value)


def number_text(number):
    """Region-independent Shortcuts number text: 1 -> '1', 0.95 -> '95E-2'."""
    if float(number).is_integer():
        return str(int(number))
    sign, digits, exponent = Decimal(str(number)).as_tuple()
    return ("-" if sign else "") + "".join(map(str, digits)).lstrip("0") + f"E{exponent}"


def text_value(*parts):
    text = ""
    attachments = {}
    for part in parts:
        if isinstance(part, dict):
            # NSRange offsets are UTF-16 code units, not Python character indexes.
            offset = len(text.encode("utf-16-le")) // 2
            attachments[f"{{{offset}, 1}}"] = part["Value"]
            text += "\ufffc"
        else:
            text += str(part)
    if not attachments:
        return text
    return {"WFSerializationType": "WFTextTokenString", "Value": {
        "string": text, "attachmentsByRange": attachments,
    }}


def dictionary_value(items):
    fields = []
    for key, value in items.items():
        if isinstance(value, dict) and "WFSerializationType" not in value:
            kind = 1
            encoded = {"WFSerializationType": "WFDictionaryFieldValue", "Value": dictionary_value(value)}
        else:
            kind = 0
            encoded = value if isinstance(value, dict) and value.get("WFSerializationType") == "WFTextTokenString" else text_value(value)
            if isinstance(encoded, str):
                encoded = {"WFSerializationType": "WFTextTokenString", "Value": {"string": encoded}}
        fields.append({
            "WFKey": {"WFSerializationType": "WFTextTokenString", "Value": {"string": key}},
            "WFItemType": kind, "WFValue": encoded,
        })
    return {"WFSerializationType": "WFDictionaryFieldValue", "Value": {"WFDictionaryFieldValueItems": fields}}


class Shortcut:
    def __init__(self, name):
        self.name = name
        self.actions = []
        self.triggers = []

    def message_trigger(self, phrase):
        self.triggers.append({
            "WFTriggerIdentifier": "WFMessageTrigger",
            "WFTriggerUUID": self.uid(f"trigger/{phrase}"),
            "WFTriggerSerializedParameters": {"WFMessageConditions": {
                "WFSerializationType": "WFContentPredicateTableTemplate",
                "Value": {
                    "WFContentPredicateBoundedDate": False,
                    "WFActionParameterFilterPrefix": 1,
                    "WFActionParameterFilterTemplates": [{
                        "Operator": 1, "Values": {"Text": phrase}, "Removable": False, "Property": "Message",
                    }],
                },
            }},
        })

    def uid(self, label):
        return str(uuid5(NAMESPACE_URL, f"iosshortcut/{self.name}/{label}")).upper()

    def action(self, identifier, name=None, **params):
        uid = self.uid(f"{len(self.actions)}/{identifier}")
        params["UUID"] = uid
        if name:
            params["CustomOutputName"] = name
        self.actions.append({
            "WFWorkflowActionIdentifier": "is.workflow.actions." + identifier,
            "WFWorkflowActionParameters": params,
        })
        return attachment({"Type": "ActionOutput", "OutputUUID": uid, "OutputName": name or identifier})

    def comment(self, message):
        self.action("comment", WFCommentActionText=message)

    def text(self, value, name=None):
        return self.action("gettext", name, WFTextActionText=value)

    def set(self, name, value):
        self.action("setvariable", WFVariableName=name, WFInput=value)
        return variable(name)

    def match(self, value, pattern, name=None):
        return self.action("text.match", name, text=text_value(value),
                           WFMatchTextPattern=pattern, WFMatchTextCaseSensitive=False)

    def replace(self, value, pattern, replacement=""):
        return self.action("text.replace", WFInput=text_value(value),
                           WFReplaceTextFind=pattern, WFReplaceTextReplace=replacement,
                           WFReplaceTextRegularExpression=True, WFReplaceTextCaseSensitive=False)

    def get(self, value, key):
        return self.action("getvalueforkey", WFInput=value, WFDictionaryKey=key,
                           WFGetDictionaryValueType="Value")

    def stop_if_blank(self, value, status, *, notify="test"):
        """Stop unless value contains a non-space character.

        iOS treats an empty Text action as having a value, so "has no value"
        cannot detect blank text; a regex match list can.
        """
        self.stop_if(self.match(value, r"\S"), NO_VALUE, status, notify=notify)

    @contextmanager
    def if_(self, value, condition, compare=None):
        group = self.uid(f"if/{len(self.actions)}")
        params = {"GroupingIdentifier": group, "WFControlFlowMode": 0,
                  "WFCondition": condition, "WFInput": {"Type": "Variable", "Variable": value}}
        if compare is not None:
            if isinstance(compare, (int, float)):
                # Shortcuts stores If numbers as text; decimals use region-independent E notation.
                params["WFNumberValue"] = number_text(compare)
            else:
                params["WFConditionalActionString"] = text_value(compare)
        self.action("conditional", **params)
        yield group
        self.action("conditional", GroupingIdentifier=group, WFControlFlowMode=2)

    def otherwise(self, group):
        self.action("conditional", GroupingIdentifier=group, WFControlFlowMode=1)

    @contextmanager
    def each(self, value):
        group = self.uid(f"repeat/{len(self.actions)}")
        self.action("repeat.each", WFInput=value, GroupingIdentifier=group, WFControlFlowMode=0)
        yield variable("Repeat Item")
        self.action("repeat.each", GroupingIdentifier=group, WFControlFlowMode=2)

    def finish(self, status, *, log=False, notify="test"):
        """Report the outcome, optionally log it, then stop this shortcut.

        notify: "always" (sent and errors), "test" (only manual test runs, so the
        automations stay silent on the many ordinary messages they see), or "never".
        """
        if not isinstance(status, str):
            status = self.text(status)
        if log:
            self.note(status)
        if notify == "test":
            with self.if_(variable("Test run"), IS, "yes"):
                self.notify(status)
        elif notify == "always":
            self.notify(status)
        self.action("exit")

    def notify(self, status):
        self.action("notification", WFNotificationActionTitle=NAME,
                    WFNotificationActionBody=text_value("Result: ", status),
                    WFNotificationActionSound=False)

    def note(self, status):
        date = attachment({"Type": "CurrentDate", "Aggrandizements": [{
            "Type": "WFDateFormatVariableAggrandizement", "WFDateFormatStyle": "Custom",
            "WFDateFormat": "yyyy-MM-dd'T'HH:mm:ssXXX", "WFISO8601IncludeTime": False,
        }]})
        self.action("file.append", WFFile=variable("Log folder"),
                    WFFilePath="events.log", WFInput=text_value(date, " ", status))

    def stop_if(self, value, condition, status, compare=None, *, log=False, notify="test"):
        with self.if_(value, condition, compare):
            self.finish(status, log=log, notify=notify)

    def document(self):
        document = {
            "WFWorkflowClientVersion": "3612.0.1.1",
            "WFWorkflowMinimumClientVersion": 1106,
            "WFWorkflowMinimumClientVersionString": "1106",
            "WFWorkflowIcon": {"WFWorkflowIconStartColor": -12365313, "WFWorkflowIconGlyphNumber": 61467},
            "WFWorkflowActions": self.actions,
            "WFWorkflowHasShortcutInputVariables": True,
            "WFWorkflowHasOutputFallback": False,
            "WFWorkflowInputContentItemClasses": [],
            "WFWorkflowOutputContentItemClasses": [],
            "WFWorkflowTypes": ["WFWorkflowTypeShowInSearch"],
            "WFQuickActionSurfaces": [],
        }
        if self.triggers:
            document["WFWorkflowTriggers"] = self.triggers
        return document


def build(stage):
    s = Shortcut(NAME)
    s.comment(
        f"Political SMS opt-out via OpenRouter Jev — stage {stage} of 3. "
        "Inspired by Tim Wilson's Auto Unsubscribe.\n\n"
        "Run it manually to test: paste a message and read the Result notification. "
        "Manual runs never send a reply.\n"
        "Stage 1: local filtering only, no network, no sending.\n"
        "Stage 2: adds the OpenRouter Jev decision, still no sending.\n"
        "Stage 3: sends the opt-out reply when Dry run is 0.\n\n"
        "Group detection is BEST EFFORT: an unknown group participant can pass. Grant FULL Contacts "
        "access. Only the message text of local candidates is sent to OpenRouter (stage 2+); no sender "
        "number or contacts. Logs hold only time and outcome."
    )
    # Reference the key Text action's output directly: a Set Variable fed a blank
    # key would fail with "choose a value for each parameter" instead of reporting it.
    key = s.text("", "OpenRouter API key") if stage >= 2 else None
    # Number action output is natively typed, so a numeric If can compare it.
    dry = s.action("number", "Dry run", WFNumberActionNumber=1) if stage >= 3 else None

    # Manual test vs. automation input. Values are checked before Set Variable,
    # because Set Variable fails on an empty input (e.g. an image-only message).
    with s.if_(shortcut_input(), NO_VALUE) as branch:
        s.set("Test run", s.text("yes"))
        s.set("Message sender", s.text(TEST_SENDER))
        answer = s.action("ask", WFAskActionPrompt="Paste a test message (no reply is sent):",
                          WFInputType="Text", WFAskActionDefaultAnswer=TEST_SAMPLE)
        s.stop_if_blank(answer, "empty_message")
        s.set("Message body", answer)
        s.otherwise(branch)
        s.set("Test run", s.text("no"))
        incoming_sender = s.text(text_value(shortcut_input("Sender")))
        s.stop_if_blank(incoming_sender, "invalid_sender")
        s.set("Message sender", incoming_sender)
        incoming_body = s.text(text_value(shortcut_input("Content")))
        s.stop_if_blank(incoming_body, "empty_message")
        s.set("Message body", incoming_body)
    sender, body = variable("Message sender"), variable("Message body")

    s.stop_if(s.match(sender, policy.SENDER_PATTERN), NO_VALUE, "invalid_sender")
    digits = s.replace(sender, "[^0-9]")
    s.stop_if(s.match(digits, r"\A[0-9]{5,15}(?![\s\S])"), NO_VALUE, "invalid_sender")
    s.set("Sender key", s.text(text_value(s.match(digits, r"[0-9]{1,10}(?![\s\S])"))))

    s.stop_if(s.match(body, policy.TRANSACTIONAL_PATTERN), HAS_VALUE, "transactional")
    s.stop_if(s.match(body, policy.POLITICAL_PATTERN), NO_VALUE, "not_political")

    # Accumulate recognized keywords in a never-empty text, then require exactly one.
    s.set("Opt-out keywords", s.text(KEYWORDS_PREFIX))
    for keyword, pattern in policy.OPT_OUT_PATTERNS.items():
        with s.if_(s.match(body, pattern), HAS_VALUE):
            s.set("Opt-out keywords", s.text(text_value(variable("Opt-out keywords"), " ", keyword)))
    single = s.match(variable("Opt-out keywords"),
                     r"\A" + KEYWORDS_PREFIX + r" (" + "|".join(policy.OPT_OUT_PATTERNS) + r")(?![\s\S])")
    s.stop_if(single, NO_VALUE, "no_opt_out")
    s.set("Opt-out keyword", s.action("text.match.getgroup", matches=single, WFGroupIndex=1,
                                      WFGetGroupType="Group At Index"))

    if stage >= 2:
        s.set("Log folder", s.action("file.createfolder", WFFilePath="AutoUnsubscribeJev"))
        s.comment(
            "Deduplicate: the 'stop' and 'end' automations both fire for texts such as 'Stop To End'. "
            "The first run records a one-way SHA256 of sender + text; a later run with the same "
            "message stops silently. Manual test runs are not recorded."
        )
        with s.if_(variable("Test run"), IS, "no"):
            # Hash takes a variable-only input: pass a Text action's output, not composed text.
            # On device, composed text produced an empty hash, so dedup never matched.
            fingerprint_source = s.text(text_value(sender, "\n", body), "Fingerprint source")
            fingerprint = s.action("hash", "Message fingerprint", WFInput=fingerprint_source,
                                   WFHashType="SHA256")
            # Without a fingerprint, duplicates cannot be detected: send nothing rather than twice.
            s.stop_if(s.match(fingerprint, r"\A[0-9a-fA-F]{64}(?![\s\S])"), NO_VALUE, "fingerprint_failed",
                      log=True, notify="always")
            seen = s.action("documentpicker.open", "Seen messages", WFGetFilePath="seen.txt",
                            WFFile=variable("Log folder"), WFFileErrorIfNotFound=False, WFShowFilePicker=False)
            with s.if_(seen, HAS_VALUE):
                s.stop_if(s.text(text_value(seen)), CONTAINS, "duplicate", fingerprint, notify="never")
            s.action("file.append", WFFile=variable("Log folder"), WFFilePath="seen.txt",
                     WFInput=text_value(fingerprint))
    s.comment("Local contact lookup only; nothing about contacts leaves the phone.")
    contacts = s.action("filter.contacts", "Local contacts", WFContentItemLimitEnabled=False,
                        WFContentItemFilter={"WFSerializationType": "WFContentPredicateTableTemplate", "Value": {
                            "WFActionParameterFilterPrefix": 1, "WFContentPredicateBoundedDate": False,
                            "WFActionParameterFilterTemplates": [],
                        }})
    phones = s.action("detect.phonenumber", "Contact phone numbers", WFInput=contacts)
    with s.if_(phones, HAS_VALUE):
        with s.each(phones) as phone:
            contact_base = s.replace(phone, policy.CONTACT_EXTENSION_PATTERN)
            with s.if_(s.match(contact_base, policy.SENDER_PATTERN), HAS_VALUE):
                contact_digits = s.replace(contact_base, "[^0-9]")
                with s.if_(s.match(contact_digits, r"\A[0-9]{5,15}(?![\s\S])"), HAS_VALUE):
                    contact_key = s.text(text_value(s.match(contact_digits, r"[0-9]{1,10}(?![\s\S])")))
                    s.stop_if(contact_key, IS, "contact", variable("Sender key"))

    if stage == 1:
        s.finish(text_value("local_candidate (", variable("Opt-out keyword"), "); stage 1 stops here"),
                 notify="always")
        return s

    s.stop_if_blank(key, "api_key_missing", notify="always")
    s.comment(
        "Jev is a decision model: /api/alpha/decisions with state/questions, not chat/completions. "
        "No generated reply text, sender metadata, fallback model, or retries."
    )
    payload = {"model": policy.MODEL, "state": {"message": body}, "questions": policy.QUESTIONS}
    response = s.action(
        "downloadurl", "Jev response", WFURL=policy.ENDPOINT, WFHTTPMethod="POST", WFHTTPBodyType="JSON",
        WFJSONValues=dictionary_value(payload), ShowHeaders=True,
        WFHTTPHeaders=dictionary_value({"Content-Type": "application/json",
                                        "Authorization": text_value("Bearer ", key)}),
    )
    response_text = s.text(text_value(response))
    s.stop_if(s.match(response_text, r'"errors?"\s*:'), HAS_VALUE, "api_error", log=True, notify="always")
    json_number = r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?"
    answer_pattern = (
        r'(?-i:\A\s*\{\s*(?:"type"\s*:\s*"noul"\s*,\s*"noul"\s*:\s*' + json_number
        + r'|"noul"\s*:\s*' + json_number + r'\s*,\s*"type"\s*:\s*"noul")\s*\}\s*(?![\s\S]))'
    )
    for question in policy.QUESTIONS:
        answer = s.get(response, f"answers.{question}")
        s.stop_if(answer, NO_VALUE, "invalid_response", log=True, notify="always")
        # Validate the documented two-field answer before Shortcuts can coerce
        # strings or booleans to numbers. JSON exponent notation is valid.
        s.stop_if(s.match(s.text(text_value(answer)), answer_pattern), NO_VALUE, "invalid_response",
                  log=True, notify="always")
        # Extract the JSON number text. Thresholds are regexes over that text: an
        # untyped dictionary value cannot be compared numerically in an If action.
        score_match = s.match(s.text(text_value(answer)), r'"noul"\s*:\s*(' + json_number + ")")
        s.set(question, s.action("text.match.getgroup", matches=score_match, WFGroupIndex=1,
                                 WFGetGroupType="Group At Index"))
    s.stop_if(s.match(variable("political_outreach"), policy.POLITICAL_SCORE_PATTERN),
              NO_VALUE, "skipped_score", log=True)
    s.stop_if(s.match(variable("transactional"), policy.TRANSACTIONAL_SCORE_PATTERN),
              NO_VALUE, "skipped_score", log=True)

    if stage == 2:
        s.finish(text_value("would_send ", variable("Opt-out keyword"), "; stage 2 never sends"),
                 log=True, notify="always")
        return s

    s.stop_if(variable("Test run"), IS, "test_run_not_sent", "yes", log=True)
    # A dry-run match is the only way to see what would have been sent, so it notifies.
    s.stop_if(dry, IS_NOT, "dry_run", 0, log=True, notify="always")
    s.action(
        "sendmessage", WFSendMessageActionRecipients=sender,
        WFSendMessageContent=text_value(variable("Opt-out keyword")), ShowWhenRun=False,
        IntentAppDefinition={"BundleIdentifier": "com.apple.MobileSMS", "Name": "Messages", "TeamIdentifier": "0000000000"},
        AppIntentDescriptor={"TeamIdentifier": "0000000000", "BundleIdentifier": "com.apple.MobileSMS",
                             "Name": "Messages", "AppIntentIdentifier": "SendMessageIntent"},
    )
    s.finish("sent", log=True, notify="always")
    for phrase in TRIGGER_PHRASES:
        s.message_trigger(phrase)
    return s


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    shortcut = build(args.stage)
    path = args.output / f"{NAME}.unsigned.shortcut"
    path.write_bytes(plistlib.dumps(shortcut.document(), fmt=plistlib.FMT_XML, sort_keys=False))
    print(f"{path}: stage {args.stage}, {len(shortcut.actions)} actions (unsigned; sign before import)")


if __name__ == "__main__":
    main()
