# Review fixes (2026-11-06)

The plan to fix the 15 findings of the code review run on 2026-11-06, before refunds handle real money. All 1517 tests passed at review time. Findings 1 and 2 were confirmed by running them.

**Status:** the three decisions took their defaults (2026-11-06). Steps 1 to 7 are done. The new review found 15 more points: see « Round 2 » at the end, where steps 8 to 10 are done; « Round 3 » has the third review's 9 points, all fixed (step 11).

## The findings

| # | Where | What goes wrong |
| --- | --- | --- |
| 1 | [services/refunds.py:107](src/tadris/services/refunds.py#L107) | A switch counts as leaving, so the old group's paid month is refundable from the day after the switch, while that same month still covers the new group (its first month starts when the old one ends). The family is paid back and the student attends for free. |
| 2 | [repositories/timetable.py:72](src/tadris/repositories/timetable.py#L72) | A closure keeps only the slots running that day. A group closed before it starts keeps none, so a month paid ahead has no session: it can't be refunded or cancelled. The money is stuck. |
| 3 | [services/refunds.py:108](src/tadris/services/refunds.py#L108) | After a closure, counting starts the day after the closing day. The closing day's session, which the closure cancels, counts as used and is never refunded. |
| 4 | [services/refunds.py:91](src/tadris/services/refunds.py#L91) | For a student still in the group, a session already attended on the day of the request counts as unused. |
| 5 | [services/refunds.py:203](src/tadris/services/refunds.py#L203) | The maximum, `approve` and the 0021 triggers ignore what archived (phase 8) refunds already handed back, while the payout does subtract it. An approved refund can then be impossible to pay out. |
| 6 | [repositories/refunds.py:41](src/tadris/repositories/refunds.py#L41) | Close, reopen and close again the same day: the closure week is stored twice and every session after it counts double. |
| 7 | [services/refunds.py:283](src/tadris/services/refunds.py#L283) | The director can approve more than the amount asked. PLAN.md says « the one asked or less ». |
| 8 | [core/money.py:84](src/tadris/core/money.py#L84) | « un million dinars » instead of « un million de dinars » on the refund receipt. |
| 9 | [services/debt.py:18](src/tadris/services/debt.py#L18) | The comment says money only sits on open charges; a cancelled, fully refunded month now breaks that. |
| 10 | [repositories/students.py:13](src/tadris/repositories/students.py#L13) | The student picker runs the Élèves list's group and standing subqueries on every keystroke. |
| 11 | [repositories/subscriptions.py:16](src/tadris/repositories/subscriptions.py#L16) | Every subscription query pays for three refund subqueries, including the Abonnements page's heaviest one. |
| 12 | [ui/pages/student_detail.py:333](src/tadris/ui/pages/student_detail.py#L333) | The student page reloads the refunds list on every change, twice after a window closes. |
| 13 | [ui/pages/dashboard.py:384](src/tadris/ui/pages/dashboard.py#L384) | The cash chart rebuilds fonts and rescans the days on every mouse move. |
| 14 | [services/refunds.py:289](src/tadris/services/refunds.py#L289) | `approve` copies the maximum formula instead of calling `_maximum`. |
| 15 | [ui/refund_dialogs.py:19](src/tadris/ui/refund_dialogs.py#L19) | Copied helpers: `_dzd`, `_title`, and the "paid by payments not voided" subquery (about 5 copies). |

## Before step 1: the migrations

Migrations 0021 and 0022 have never been committed, and PLAN.md says no database here has a closed group or an archived refund. So both files are edited in place instead of adding a 0023. The migration runner only tracks version numbers, so any database that already ran them (the dev database, the demo seed) has to be rebuilt.

## Three decisions (default in bold)

1. **Refund only after the student has left the group.** Today a student still in a group can be refunded from the day of the request. That rule causes findings 1 and 4: after the refund, nothing stops the student from coming, either to the same group or to the new group after a switch. With this default, the desk records the leave first (dated yesterday if today's session hasn't happened yet), then asks for the refund.
   - This changes the rule set on 2026-11-06 in PLAN « Refunds in V1 ».
   - To keep that rule instead, step 1 follows the switch to the new group and doesn't count a session already held on the request day.
2. **A month with no session at all can be refunded in full if none of it was used.** This covers a group with no timetable or a month that is all holidays. Today that money is stuck: it can't be refunded (no session) and the month can't be cancelled (money still kept).
3. **The director approves the amount asked or less**, as PLAN.md says. Today the code allows up to the maximum, and a test relies on that.

## Step 1: when the unused sessions start (findings 1, 3, 4) — done

Done 2026-11-06. What was built differs from the plan below in three details:

- The repository queries are `place_now` (the last enrollment after all switches) and `session_held`.
- A month the student still follows comes back from `refunds.options` with `max_amount` 0, no count (`sessions` is None) and `still_in` naming the group. The dialog shows that group with « Sortir du groupe ».
- In the tests, a `gone()` helper records the student's last day as the day before the request. The counts and dates the existing tests expect stay the same.

Not yet done: the case of a switch to a group that starts later still has to be written in PLAN.md (step 7).

New rule in [services/refunds.py:104](src/tadris/services/refunds.py#L104):

| Situation | Counting starts |
| --- | --- |
| Still in the group, or switched and still in the new group | Refused: record the leave first (decision 1) |
| Left, or left the last group after one or more switches | The day after the last day, as today |
| Left because the school closed the group | The closing day, or the entry day if the group closed before the student started. The next day if a session was already held that day |

"Held" means a session of that group that day with status `held` or with attendance taken. A session the closure cancelled was not held, so it gets refunded (finding 3).

- **[repositories/refunds.py](src/tadris/repositories/refunds.py):** add two queries.
  - `chain_end`: a recursive query on `switched_from_id` that returns the last enrollment after all switches (status, `left_on`, entry day, group).
  - `held_on(group, day)`.
- **[services/refunds.py](src/tadris/services/refunds.py):**
  - `first_unused_day` reads the last enrollment after all switches.
  - `request` refuses with a new message naming the group, and `options` gives 0 for those months.
  - A month is still priced on its own group's timetable.
  - The `on` parameter goes away.
- **[ui/refund_dialogs.py](src/tadris/ui/refund_dialogs.py):** when there is no month to offer, the dialog says why (still in group X).
- **Write in PLAN.md:** after a switch to a group that starts later, the days in between count as used.
- **Tests:**
  - The reviewer's switch case: A's September, and an October paid ahead in A, both give 0 while the student is in B. After the student leaves B on 20/09, the count starts 21/09 on A's timetable.
  - A group closed Monday morning: Monday's session is refunded.
  - A group closed Monday evening after the session was held: that session is not refunded.
  - A group closed before the student's first day.
  - The test helpers record a leave before asking for a refund.

## Step 2: a closure keeps the coming weeks (findings 2, 6) — done

Done 2026-11-06, as planned below. Notes on what was built:

- **Closure that ended a place:** it is found from `group_closures`, so the closing-day rule from step 1 still applies after a reopen.
- **Planned end:** the app can't create a slot with a planned end yet (`update_slot` always takes effect today), so that case has a pure test of `until_closure` only.
- **No-session months (decision 2):** the dialog and the receipt say « Aucune séance… rien n'en a été utilisé » instead of « 0 séance(s) sur 0 ».
- **Local databases:** both were still at version 20, so they never ran the old 0021 or 0022 and need no rebuild.

Rewrite 0022 so each closure gets its own row:

- New table `group_closures(id, group_id, closed_on)`. Its rows can't be changed.
- `class_groups.closure_id` replaces `closed_on`. It is NULL while the group is open or after a reopen.
- `group_closure_slots` points to its closure and also keeps each slot's `valid_from` and `valid_to`.
- Groups closed before 0022 get one closure row each, with the day taken from the audit log as now.

Code changes:

- **`keep_for_closure`** ([repositories/timetable.py:63](src/tadris/repositories/timetable.py#L63)): keep every slot running on the closing day or planned to start later (`valid_to IS NULL OR valid_to > :on`), with its own dates. This fixes the group closed before it starts.
- **`until_closure`:** from the closing day, each kept slot counts over `[max(valid_from, closed_on), valid_to)`. A slot planned to start or end later is counted only within those dates.
- **Closure lookup:** `release` ([services/groups.py:240](src/tadris/services/groups.py#L240)) creates the closure row and `reopen` clears `closure_id`. The refund count reads its closure by id, so closing, reopening and closing again the same day counts the week only once.
- **Decision 2:** `count_left` gives the full price when the month has no session and counting starts on or before its first day. Relax 0021's `CHECK (sessions_total > 0)` to match.
- **Tests:**
  - The reviewer's group C case: closed 20/09, due to start 01/10, October paid. 6 000 DA is refundable, and once refunded the month can be cancelled.
  - A running group with a slot planned to start later.
  - Close, reopen and close again the same day.
  - A slot with a planned end.

## Step 3: refund limits (findings 5, 7, 14) — done

Done 2026-11-06, as planned below. Notes on what was built:

- **Display:** `RefundableMonth.held` now includes what the archive handed back, so the dialog's « Déjà remboursé ou demandé » line shows it. A request's audit line records it as `archived` when it isn't zero.
- **Approve dialog:** a new note says « Le montant demandé ou moins : au plus … ».
- **Tests rewritten:** the service and trigger tests that approved more than asked now check the refusal. A new test shows that approving less frees the rest for another request.
- **Old databases:** the archive's cap is tested on a version 14 database migrated forward, by the trigger and through the service (request, approve, pay out).

- **Archived refunds:** `open_charge` and `paid_months` also return `archived`, the money old phase 8 refunds already handed back on the month.
- **One maximum formula:** a single `_maximum(value, paid, archived, held)` = `max(min(value, paid − archived) − held, 0)`. Both `request` and `approve` call it, which removes the copy at [services/refunds.py:289](src/tadris/services/refunds.py#L289).
- **0021 triggers:** at request and at approval, the "paid minus already refunded" checks also subtract the archived amount.
- **Decision 3:**
  - `approve` refuses more than the amount asked, with a new message.
  - 0021 changes to `amount_approved BETWEEN 1 AND amount_requested`.
  - The approve dialog's maximum becomes the amount asked.
  - [tests/test_refunds.py:316](tests/test_refunds.py#L316) becomes a refusal.
  - Fix the comment at [services/refunds.py:23](src/tadris/services/refunds.py#L23).
- **Tests:**
  - A 6 000 DA month with 2 000 DA archived gives a maximum of 4 000.
  - A 4 500 DA request is refused by the service and by the trigger.
  - Approving 2 500 on a 2 000 DA request is refused.

## Step 4: wording and comments (findings 8, 9) — done

Done 2026-11-06. Notes on what was built:

- **Where the « de » tests went:** next to the other amount-in-words tests, in `tests/test_refund_receipt.py`, not in `tests/test_core.py`.
- **Money queries checked:** what's owed, the open-charges list, Recettes and the dashboard all filter on open charges. The sums per payment (`allocated`, a payment's allocations) still include a cancelled month, and that's right: they are the payment's own record, which a refund never changes.
- **Guard test** (`test_refunds_money.py`): October refunded in full, then cancelled. Its allocation stays on the cancelled charge, nothing is owed, and it drops out of Attendu, Payé and the teacher's share.

- **« de » after million** ([core/money.py:82](src/tadris/core/money.py#L82)): add « de » when the amount is a whole number of millions.
  - « un million de dinars », « deux millions de dinars », « un milliard de dinars ».
  - But « un million deux cent mille dinars ».
  - Tests go in `tests/test_core.py`.
- **Debt comment** ([services/debt.py:18](src/tadris/services/debt.py#L18)): say that a month refunded in full can be cancelled with its payments still allocated to it, so code that adds up money must only count open months.
  - Reports, dashboard and payments already do this (`c.status = 'open'`).
  - Add one test: a cancelled, refunded month adds nothing to the debt, « Attendu » or « Payé ».
- **Outdated comment:** remove « V1 has no refunds » at [services/enrollments.py:31](src/tadris/services/enrollments.py#L31).

## Step 5: speed (findings 10–13) — done

Done 2026-11-06. What was built differs from the plan below in three places:

- **Student search:** `details` defaults to True, and the student picker passes `details=False`. Every other caller keeps the full rows. Sorting by groups or by standing still works them out.
- **Subscriptions:** the school-wide lists return the refund columns as NULL, not 0. A month read from them raises if asked whether it can be cancelled, instead of quietly saying yes.
- **Which months read refunds:** `for_enrollment` reads them too, along with `get`, `for_student` and `starting_after`. It's only ever one enrollment's few months, and a payout test decides « Annuler » from it.

- **Student search:** add `search(..., details=False)`. Only the Élèves list asks for groups and standing. The student picker gets `NULL` instead of the two subqueries.
- **Subscriptions:** move the refund columns to `_REFUND_COLUMNS`, used only by:
  - `get`
  - `for_student`, for the « Annuler » button in the months list
  - `starting_after`, for the cancel audit

  The other queries select `0 AS refunded, 0 AS refund_open`.
- **Student page** ([ui/pages/student_detail.py:333](src/tadris/ui/pages/student_detail.py#L333)):
  - `refresh_overview` reads a count (new `refunds.count_for_student`) instead of reloading the whole list.
  - `open_window` stops reloading the refunds after the window closes; the window already reloads them when it opens.
- **Dashboard chart** ([ui/pages/dashboard.py:384](src/tadris/ui/pages/dashboard.py#L384)): work out the grid step and gutter once in `set_days`; `_plot` reads the stored values.

## Step 6: shared helpers (finding 15) — done

Done 2026-11-06. Where each shared helper went:

- **SQL fragments:** `repositories/charge_money.py` has `paid_on`, `archived_on` and `handed_back_on`. Each takes the SQL of the charge's id, by default `c.id`. They replace 7 copies of "paid by payments not voided" (the payments, subscriptions, dashboard, reports, registrations and refunds repositories, 2 in refunds), the archive sum, and the subscriptions repository's « handed back » sum.
- **Amount in a sentence:** `core.money.dzd_inline` replaces both `_dzd` copies and one inline copy in `ui/subscription_dialogs.py`.
- **Group title:** `core.text.group_title(row, name="group_name")` replaces 7 copies: `_title` in refunds, subscriptions and payouts; `_group_title` in enrollments; and the inline strings in attendance, payments and sessions.
- **Tests:** `test_core.py` tests the two public helpers. The test helper `in_sentence` keeps its own copy on purpose, so the tests still check against something independent.

- **Amount in a sentence:** one `core.money.dzd_inline` (amount with non-breaking spaces) replaces both `_dzd` copies.
- **Group title:** one `group_title(row)` replaces `refunds._title`, `subscriptions._title` and the same string built in enrollments and sessions.
- **Money subqueries:** one SQL fragment for "paid by payments not voided" and one for "handed back", used by the payments, subscriptions, dashboard, reports and refunds repositories. The triggers keep their own copies, since SQL triggers can't share code.

## Step 7: finish — done (the new review's findings are in « Round 2 »)

Done 2026-11-06:

- **Docs:** PLAN.md has the new status, the three decisions and the switch edge case. The README says a refund comes once the student has left, and that the director approves the amount asked or less.
- **Seed:** `scripts/seed_demo.py` seeded a fresh demo school in the scratchpad, not `data/demo.db`. It reached version 22 with a clean integrity check.
- **Check by hand:** done offscreen on a copy of that demo, through the real dialogs, with screenshots. Neither real database was touched.
  - **Switch, then refund:** while the student is in the new group, nothing is offered and the request is refused. After the leave, the old group's month is offered.
  - **A group closed before it starts:** its month paid ahead (4 500 DA) goes through request, approval, payout and receipt, then gets cancelled.
  - **1 000 000 DA:** refunded and printed.
- **Found by the check, fixed:** the receipt said « Arrêté à la somme **de un** million de dinars ». `core.money.of_dzd_in_words` now elides it: « d'un million », « d'un dinar ».
- **Seen, not changed (cosmetic, and they were already there):**
  - In the request dialog, the month list cuts the end of a long entry (« … (au plus 3 555 DA »).
  - On the receipt, a 7-digit total puts « DA » on a second line in the TOTAL box.

- Update the « Refunds in V1 » section of PLAN.md (count rule, closures, archived refunds, the three decisions) and the README.
- Rebuild the dev database, re-run `scripts/seed_demo.py`, run the full test suite.
- Check by hand in the app:
  - switch groups, then try a refund
  - close a group that hasn't started, refund, pay out
  - print a 1 000 000 DA receipt
  - cancel the refunded month
- Run `/code-review` again on the result.

Steps 1 to 3 are the real work and the only ones blocking real money. Steps 4 to 6 are small.

---

# Round 2: the review of the fixes (2026-11-06)

`/code-review` was run again on the result of steps 1 to 7. All 1544 tests passed. It found 15 more points, and the first three were reproduced with probe tests. Some are gaps in this round's own work: findings 2, 3, 6, 7 and 9 below come from steps 1, 2 and 6, and finding 13 is a case step 5 missed. The **Round 2 status** line at the end of this section says what is done.

## The findings

| # | Where | What goes wrong |
| --- | --- | --- |
| 1 | `services/refunds.py:150` | Decision 1 needs a recorded leave, but a leave before the entry date is refused. A month paid ahead for a group the student hasn't started can't be refunded until the group starts. Then the first session counts as used (6 000 DA paid, 4 800 DA back). |
| 2 | `services/refunds.py:186` | After a reopen, the count uses the group's current closure (none), not the one that ended the student's place. The sessions the closure took away count for nothing: September goes from 3 000 DA to 0. |
| 3 | `repositories/timetable.py:72` | Close, reopen, close again the same day without adding a slot back: the second closure keeps no slots, and the group points to it. The count drops to 0. |
| 4 | `services/printing.py:48` | New refund ids restart at 1, and the print log uses the same type « refund » as the phase 8 slips. New refund #1 would print as DUPLICATA on a database that printed old slip #1. Old « refunds » journal entries also mix with the new ones. |
| 5 | `i18n/fr.py:1333` | The leave dialog still says « Mois à venir gardés (pas de remboursement) », while decision 1 makes leaving the first step of a refund. |
| 6 | `repositories/refunds.py:45` | The closure that ended a place is guessed from dates. In a group closed and reopened before the student's entry, leaving on one's own on the entry day is taken for a closure. |
| 7 | `services/refunds.py:149` | « Held » is checked per day, not per session. With two sessions on the closing day, one held in the morning and one cancelled by the closure, the cancelled one is never refunded. |
| 8 | `services/refunds.py:331` | The new `archived` key in the request's audit line has no French label and isn't formatted as money in the Journal. |
| 9 | `repositories/refunds.py:171` | The `paid_on` SQL helper imported in step 6 is shadowed by the repository's own `paid_on(conn, day)`. It works now only because of where it is used. |
| 10 | `0021_refunds_v1.sql:126` | The update trigger doesn't stop a step from setting another step's fields. An approval can carry a payout number, a method or a cancel author. |
| 11 | `i18n/fr.py:446` | `refund_dialog.none` and `refund.no_session` still describe the rule from before decision 2. |
| 12 | `ui/pages/subscriptions_tab.py:109` | « V1 has no refunds » remains in three comments: `subscriptions_tab.py:109`, `services/dashboard.py:18` and `services/registrations.py:142`. |
| 13 | `ui/pages/refunds_section.py` | The section still loads its list when the student page is built (not only when its window opens). On Paiements, each action reloads the queue twice. |
| 14 | `services/refunds.py:308` | `request` reads the month twice. `options` runs about 5 queries per month, the same enrollment chain included. |
| 15 | `ui/pages/dashboard.py:395` | `CashChart._top()` and `refund_dialogs.month_text` are wrappers that add nothing. |

## One decision (default in bold)

4. **A place not started yet can be left before its entry day, and its month paid ahead is then refunded in full.** « Sortir du groupe » on such a place records the entry day as the last day, even though it is still to come. The count then starts on that day itself, since no session was held. Today the leave is refused before the entry date, so the family waits for the group to start and loses its first session.

## Step 8: money (findings 1, 2, 3, 4, 6, 7) — done

Done 2026-11-06 by another agent, then reviewed here. What was built differs from the plan below:

- **New migrations, not edits in place:** `data/demo.db` had already run 0021 and 0022 (it is at version 22 and holds a refund), so they can no longer change.
  - **0023:** `enrollments.closure_id` with its triggers. The backfill sets it only when exactly one closure matches the dates. It also re-creates both refund triggers with the locks on step fields (finding 10 of step 9), and starts the new refund ids after the archive's.
  - **0024:** `enrollments.never_started` for a place left or closed before its entry day, so it sits on no session. The two attendance triggers are replaced: same checks, plus `never_started = 0`.
- **The date window:** every query that reads it goes through `repositories.enrollments.on_day()`: the attendance list, the headcount expected, attendance triggers, student clashes and makeup room counts.
- **The whole switch chain is counted** (`place_chain`), not only its last place:
  - every day a started place covered is used;
  - a place left before it started covers no day;
  - the last day is « open » only for a closure, or for a place that ended on its entry day when no earlier place covered that day.
  - This fixes a same-day switch (4 500 DA, not 6 000) and leaving a later-starting group before it starts.
- **Sessions the school cancelled:** the agent also added them back to what is left. That wasn't in the plan, and PLAN puts it beyond V1. The review found two over-refunds, each 4 500 DA instead of 3 000:
  - a session that was made up and attended;
  - a cancellation in the old group after a switch.

  It was removed. Every session before the count, cancelled by the school or not, is used. Both cases are now tests.
- **Left as they are:**
  - 0023's backfill can still tag a voluntary leave on the same day as the group's only closure. This only affects databases that reach 0023 with closed groups; the demo has none.
  - `place_now` is now unused; it goes in step 10.

- **Decision 4:** `enrollments.leave` accepts a place not started yet (no attendance). It records `left_on` = the entry day and frees the seat now. The count starts on the entry day.
- **The closure that ended a place is stored, not guessed (findings 2, 3, 6):**
  - In 0022: `enrollments.closure_id`, set by `end_live_for_group` and checked by a trigger against the enrollment's own group.
  - The refund count uses that closure's slots for the student's own group, even after a reopen.
  - Students removed by a first closure keep its slots, even if a second closure the same day keeps none.
  - Groups closed before 0022 get a backfill.
- **Per session, not per day (finding 7):** `count_left` takes how many sessions were already held on the first day, and only those count as used.
- **Ids (finding 4):** 0021 starts the new `refunds` ids after the archived ones (`sqlite_sequence`), so the print log and the Journal never mix them.
- **Tests:** the three probe cases from the review, plus a group meeting twice on the closing day.

## Step 9: texts and safety (findings 5, 8, 9, 10, 11, 12) — done

Done 2026-11-06. The other agent had already made most of these changes along with step 8 (its summary said otherwise). This step checked each one and fixed two texts:

- **Already right, with tests:**
  - « Mois à venir gardés : … ; un mois payé peut ensuite être remboursé »;
  - the 3 outdated comments;
  - `audit.key.archived` shown as money in the Journal;
  - the fragments imported as `charge_money`, so `paid_on` is no longer shadowed;
  - the step-field locks (0023), with a French message for every new trigger refusal.
- **Fixed here:**
  - `refund_dialog.none` was a sentence fragment. It now reads « Seul peut l'être un mois payé en entier, une fois l'élève sorti du groupe, s'il en reste des séances (ou, sans aucune séance à l'emploi du temps, s'il n'a pas servi) ».
  - The docstring of `registrations.cancel` read « while part of something was paid ».
- **Looked at offscreen on the demo:** the leave dialog for a place not started yet (no date field, a sentence instead), and the refund dialog with no month to offer.

- **Leave dialog:** « Mois à venir gardés : … ; un mois payé peut ensuite être remboursé ».
- **Decision 2 messages:** rewrite `refund_dialog.none` and `refund.no_session`.
- **Comments:** remove the 3 outdated comments.
- **Journal:** `audit.key.archived`, shown as money.
- **Shadowed import:** import the fragments as `charge_money` in `repositories/refunds.py`.
- **0021 trigger:** payout fields only when paid, cancel fields only when cancelled, `close_reason` only when rejected or cancelled. Add a new error message. Already done by 0023 (step 8).

## Step 10: speed and cleanup (findings 13, 14, 15) — done

Done 2026-11-06. The other agent had already made most of it:

- **Lazy list:** a student's refunds list loads only when its window opens.
- **One reload on Paiements:** after a refund action, the queue reloads once.
- **Fewer queries:** `options` reads each switch chain once, and `request` reads the month once.
- **Wrappers:** `_top()` and `month_text` are gone.

Added here:

- **Unused code:** `place_now` is removed.
- **Debtors:** Paiements no longer reloads the debtors list after a refund action, since a refund never changes what is owed.
- **Offscreen check, again:** same results as in step 7, on the demo migrated to version 24:
  - the same-day switch counts from the next day;
  - the group closed before it starts refunds its month in full;
  - the receipt reads « d'un million de dinars »;
  - the integrity check is clean.

- **Lazy list:** a student's `RefundsSection` loads its list only when its window opens. On Paiements, an action reloads the queue once.
- **Fewer queries:** `request` reads the month once; `options` reads each enrollment chain once.
- **Wrappers:** remove `_top()` and `month_text`.
- **Then:** full suite, the offscreen check again, and a third `/code-review`.

**Round 2 status:** steps 8 to 10 done (2026-11-06), with decision 4 taken (the default). The third `/code-review` found 9 more points: see « Round 3 ».

---

# Round 3: the review of round 2 (2026-11-06)

A third `/code-review` ran on the result of steps 8 to 10. All 1570 tests passed and ruff was clean. It found 9 points: 4 about money or the database, 5 cleanups. Findings 1 and 2 were reproduced with probe tests here.

| # | Where | What goes wrong |
| --- | --- | --- |
| 1 | `services/refunds.py:186` | When the last day is open, its sessions already given are looked for in the month's group, but after a switch the student spent that day in the last group. Probe: A on Thursdays, October paid ahead, switch to B (starts 01/10); the student attends B on 01/10 and leaves that day. October is counted 5 of 5 (6 000 DA) instead of 4 of 5 (4 800 DA). |
| 2 | `repositories/refunds.py:61` | `held_count` and `attended_on` count a makeup as one of that day's timetable sessions. Probe: Mondays 17:00, the 7th made up on Monday 14 at 10:00, the group closed at noon. The 17:00 session the closure dropped counts as used: 3 000 DA instead of 4 500. |
| 3 | `0021:58`, `0023:184` | `HAVING` without `GROUP BY` needs SQLite 3.39 or later. On an older system SQLite (Ubuntu 22.04 has 3.37), the migration aborts and the app can't start. Here: 3.46. |
| 4 | `0024` | `never_started` gets no backfill. A place that a closure under 0022 or 0023 ended before its entry day isn't marked. If the group is reopened with slots, that place shows on the entry day's list. |
| 5 | `services/refunds.py:330` | `options` reads `repo.month` and `repo.held` again for each paid month (N+1). |
| 6 | `repositories/refunds.py:69` | `attended_count` is dead code. |
| 7 | `services/refunds.py:219` | `sessions_left` is public, with no `ctx` and no permission check. Only the service and the tests use it. |
| 8 | `services/refunds.py:148` | `LIVE` is a copy of `services.enrollments.LIVE` (and of `_LIVE` in `repositories/timetable`). |
| 9 | `repositories/students.py:19` | The order of the standings (ended, none, expiring, active) is written 3 times in the students list. This is outside refunds. |

## Step 11: fix round 3 — done

Done 2026-11-06, all 9 points, the two optional ones included:

- **Finding 1:** on an open last day, the sessions already given are looked for in the last started place's group. They are held there for a closure, attended there otherwise. `count_left` still caps them by the month group's sessions that day.
- **Finding 2:** `held_count` and `attended_on` count only timetable sessions (`source = 'generated'`).
- **Finding 3:** both `sqlite_sequence` seeds (0021, 0023) are written without `HAVING`, with the same result. A test now refuses any `HAVING` without `GROUP BY` in a migration.
- **Finding 4:** 0024 marks `never_started` on the places a closure ended before their entry day. It was edited in place, since no database had run 0024.
- **Finding 5:** `paid_months` returns what the count needs (the month's group, its closure, its year's end, what is held), so `options` reads each switch chain once and nothing more per month.
- **Findings 6, 7, 8:** `attended_count` is removed; `sessions_left` is now the internal `_sessions_left`; `LIVE` comes from `services.enrollments`.
- **Finding 9:** the students list builds the standing column and its sort order from `STANDINGS_BY_URGENCY`. The SQL it produces is the same as before.
- **Tests:** the two probes are now tests (4 800 DA and 4 500 DA), plus the backfill on a version 23 database and the `HAVING` guard.
- **Offscreen check:** same results as before.

- **Finding 1:** on an open last day, look for the sessions already given in the last place's group: held there for a closure, attended there otherwise. Cap them by the month group's timetable sessions that day.
- **Finding 2:** count only timetable sessions (`source = 'generated'`); a makeup on that day no longer counts as one.
- **Finding 3:** rewrite both seeds without `HAVING`, with the same result. No database is harmed: the statement does the same thing.
- **Finding 4:** add the `never_started` backfill to 0024, in place: no database has run 0024 (`data/demo.db` is at version 22, your database at 20).
- **Findings 5, 6, 8:**
  - `paid_months` returns what the count needs (the month's group, its closure, its year's end, what is held), so `options` runs no extra query per month;
  - remove `attended_count`;
  - import `enrollments.LIVE`.
- **Findings 7 and 9 (optional):**
  - for 7, make `sessions_left` internal (`_sessions_left`); the tests reach it under that name;
  - for 9, build both orderings from `STANDINGS_BY_URGENCY`.
- **Then:** the two probes as tests, full suite, offscreen check.

**Round 3 status:** step 11 done (2026-11-06).
