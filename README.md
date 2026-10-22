# Auto Unsubscribe — political texts, with OpenRouter Jev

[![test](https://github.com/compumaster/ios-shortcuts-political-messages-with-jev/actions/workflows/test.yml/badge.svg)](https://github.com/compumaster/ios-shortcuts-political-messages-with-jev/actions/workflows/test.yml)

An Apple Shortcut that automatically replies `STOP` or `END` to unwanted **political** text messages, and leaves everything else alone.

It runs entirely in the Shortcuts app on your iPhone; no server, Mac, or extra app is needed. Messages are filtered on the phone first. Only likely political opt-out messages are sent to [OpenRouter's Jev](https://openrouter.ai/~typesafe/jev-latest) decision model for a final check, which costs a tiny fraction of a cent per message.

Tested on an iPhone 13 running iOS 27. Earlier iOS versions are untested.

## What it does

1. A Message automation runs the shortcut when a text contains `stop` or `end`.
2. **On the phone:**
   - accept only messages from a phone number;
   - skip medical, appointment, account, security, delivery, payment, and similar transactional texts;
   - require political wording;
   - require **exactly one** clear opt-out instruction;
   - skip senders saved in your Contacts.
3. **Jev:** only the message text of the remaining candidates is sent to Jev, which scores whether it is mass political outreach and whether it is transactional. The reply is sent only if political ≥ 0.95 and transactional ≤ 0.05.
4. It replies with the standard keyword named in the instruction, `STOP` or `END` for example. Jev never writes the reply.

Opt-out instructions it recognizes include: `Reply STOP`, `Text “STOP” to unsubscribe`, `Stop To End`, `STOP2END`, `stoptoquit`, `stoptooptout`, `END2END`, `endtoend`, `END2STOP`, “Reply END to quit”, and “Reply END2END to opt out”. Combined tokens reply with their first standard keyword: `END2END` → `END`, `STOP2END` → `STOP`. Carrier rules require senders to honor those keywords. Ordinary sentences such as “stop by after school”, “stop corruption”, or “our END2END campaign” are ignored.

## Install

You need an iPhone and an [OpenRouter](https://openrouter.ai) account with a small amount of credit.

1. On your iPhone, download [`Auto Unsubscribe - Jev.shortcut`](https://github.com/compumaster/ios-shortcuts-political-messages-with-jev/raw/main/dist/Auto%20Unsubscribe%20-%20Jev.shortcut) and open it to add it to Shortcuts. Keep the name exactly **Auto Unsubscribe - Jev**.
2. Create an [OpenRouter API key](https://openrouter.ai/settings/keys); a dedicated key with a low spending limit is best. Open the shortcut's editor and paste the key into the top Text action, **OpenRouter API key**.
3. Leave **Dry run**, the Number action below the key, at **1** for now. Dry run checks messages but never sends a reply.
4. Check the automations. The shortcut includes two Message triggers, **Message Contains `stop`** and **Message Contains `end`**. In the Automation tab, confirm both exist, set them to **Run Immediately**, and turn off **Notify When Run** if shown. If they are missing, create each by hand: Automation → **+** → **Message** → **Message Contains** `stop` (no Sender filter) → Run Immediately → **Run Shortcut** → **Auto Unsubscribe - Jev**, with the received message as input. Repeat for `end`.
5. When prompted, allow **full** Contacts access, OpenRouter (`openrouter.ai`), Files, and sending Messages.
6. If you used an older auto-unsubscribe shortcut, disable its automations so both don't reply.

### Test, then turn it on

| Test | Dry run | Expected |
| --- | --- | --- |
| Run the shortcut manually and keep the pre-filled sample | any | `test_run_not_sent`; manual runs never send |
| Someone **not** in your contacts texts: “Paid for by Friends of Candidate. Donate to our election campaign and vote this November. Reply STOP to opt out.” | 1 | One `dry_run` notification |
| A saved contact sends the same text | 1 | Nothing |

When the tests look right, set **Dry run = 0**. Replies are now automatic. Set it back to 1 at any time to pause.

### Results

Automation runs are silent unless something is sent or goes wrong. Manual runs show every result.

| Result | Meaning |
| --- | --- |
| `sent` | Opt-out reply sent |
| `dry_run` | Would have sent, but Dry run is 1 |
| `contact`, `transactional`, `not_political`, `no_opt_out`, `skipped_score`, `duplicate` | Normal skip; nothing sent |
| `api_key_missing`, `api_error`, `invalid_response`, `fingerprint_failed` | Setup or API problem; nothing sent |

## Privacy

- Message text, sender numbers, and contacts are checked **on the phone**. Only the text of candidates that pass every local check is sent to OpenRouter and Jev's provider. The sender's number and your contacts are never sent. Review [OpenRouter's privacy policy](https://openrouter.ai/privacy).
- `iCloud Drive/Shortcuts/AutoUnsubscribeJev/events.log` holds only `timestamp outcome` lines.
- `iCloud Drive/Shortcuts/AutoUnsubscribeJev/seen.txt` holds one SHA256 hash per candidate message. It prevents duplicate replies when a text contains both `stop` and `end`, such as “Stop To End” or “Friends …”, and both automations fire. Hashes cannot be turned back into text or numbers. Deleting the file is safe.
- Once you add your key, the shortcut contains it: don't share your configured copy.

## Limitations

- **Group chats are best-effort.** Message automations expose no reliable group-chat flag. A political message from an unknown group participant can pass the checks.
- **Filters are deliberately conservative and English-only.** Some genuine political spam is skipped, for example outreach that mentions healthcare, payments, or appointments, or unusually worded opt-out instructions. Unfamiliar appointment wording could slip past the local filter; Jev's transactional score is the second safeguard.
- **No accuracy guarantee.** The 0.95 and 0.05 thresholds are conservative, not measured accuracy. `~typesafe/jev-latest` is a moving alias on an alpha API, so behavior can change.
- **Duplicates are detected per message**, not per number. A new message from a number you already opted out of is handled again. An identical message from the same number is ignored.
- Numbers are compared by their last ten digits; collisions conservatively skip extra senders.
- Replying confirms that your number is active. An opt-out instruction does not make a sender trustworthy.

## Disclaimer

This sends text messages from your phone automatically. Review the test results before setting Dry run to 0. It is provided as is, without warranty; see [LICENSE](LICENSE). It is not affiliated with Apple, OpenRouter, or TypeSafe.

## Development

Everything is generated from Python with the standard library only, Python 3.10 or newer:

| File | Purpose |
| --- | --- |
| `policy.py` | Shared rules: sender, transactional, political, and opt-out patterns, plus Jev questions and score thresholds |
| `test_policy.py` | Policy tests: `python -m unittest -v test_policy` |
| `build_shortcut.py` | Generates the native shortcut: `python build_shortcut.py --stage 3` |
| `sign_shortcut.py` | Signs `dist/*.unsigned.shortcut` on a Mac: `python3 sign_shortcut.py dist` |
| `dist/` | The signed shortcut for installation. Unsigned build output is not committed. |

`--stage` builds a reduced shortcut for step-by-step device testing: **1** local filtering only, no network; **2** adds the Jev call but never sends; **3** is the full shortcut. Manual runs ask for a test message in every stage.

Unsigned shortcuts cannot be imported on iOS. Without a Mac, upload the unsigned file, **with the key blank**, to [Shortcuty Signing](https://sign.shortcuty.app/). Its [API documentation](https://github.com/Shortcuty/Signing-Server-API-Documentation) requires no account. Rename the download to `Auto Unsubscribe - Jev.shortcut`. This uploads the workflow source to Shortcuty. After changing the shortcut, re-sign it and commit the signed file.

### Jev

Jev is a decision model, not a chat model. The shortcut calls `POST https://openrouter.ai/api/alpha/decisions` with `model: "~typesafe/jev-latest"`, `state: {"message": …}`, and two `noul` questions defined in `policy.py`. Each question states a factual proposition and tells Jev to treat instructions inside the message as untrusted evidence. See OpenRouter's [Decisions API recipe](https://openrouter.ai/docs/cookbook/building-agents/gate-tool-calls-with-jev).

### Shortcuts quirks found on device

These cost real debugging time and are encoded in `build_shortcut.py`:

- **Empty values break actions.** Set Variable, Count, Repeat, and similar actions fail with “Please choose a value for each parameter” when an input is empty. Values are checked before assignment.
- **An empty Text action counts as “has any value”.** Blank text is detected with a regex match instead.
- **Numeric If needs a typed Number.** A numeric If on an untyped Dictionary Value shows “is less than” with no usable value. Jev scores are compared as JSON number text with regexes; `test_policy.py` checks them against the numeric thresholds.
- **If numbers are stored as text** (`"0"`); decimals use E notation (`95E-2`) to avoid region-specific decimal separators.
- **Condition codes:** 4 is, 5 is not, 99 contains, **999 does not contain**, 100 has any value, 101 does not have any value.
- **Run Shortcut targets** need `WFWorkflow`, not only the legacy `WFWorkflowName`. This project avoids cross-shortcut calls entirely.
- **Hash** accepts only a variable input. Composed text silently produced an empty hash.
- **Import questions** made “Add Shortcut” hang; settings are plain actions instead.
- Message triggers embedded as `WFWorkflowTriggers` appear as automations on import, in iOS's own export format.
- With two automations matching one message, iOS ran them one after another, about 9 seconds apart, which makes the file-based duplicate check reliable.

## Credits

Inspired by Tim Wilson's 2024 “Auto Unsubscribe” political-spam shortcut, which used an external AI proxy (since shut down) and Gemini. This project is a rewrite: the code is new; the idea and the opt-out phrase list come from his shortcut.

Native action schemas were cross-checked against the [Cherri](https://github.com/electrikmilk/cherri) Shortcuts compiler.

## License

[MIT](LICENSE)
