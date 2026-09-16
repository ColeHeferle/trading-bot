# Exercise 05 — broker

Rewrite `src/trading_bot/broker.py` from its tests. Do this one last.

Everything before it was arithmetic you could verify by thinking hard. This one
is about a network you do not control, a counterparty that can lose your
request after acting on it, and money that moves when you get it wrong. It is
the module that will actually make you employable, because the failure modes
here — idempotency, retry safety, error taxonomies, reconciliation — are the
failure modes of every backend job you will interview for.

Give it a week.

## Activate

```bash
python exercises/stub.py broker
```

## Baseline

`62 failed, 337 passed` — 53 in `tests/test_broker.py`, 9 in
`tests/test_live.py`.

Contained, unlike exercises 02 and 04: `broker.py` sits at the edge of the
system, so almost nothing depends on it. Being at the edge is exactly why it
is the hardest.

## Read this before you write a line

`tests/test_broker.py` lines 22–72 define `FakeTransport`. **That class is the
contract.** It is the only description you get of what the HTTP layer hands
your code, what it raises, and how a duplicate order comes back. Read it twice
before you read a single test.

You are not writing the HTTP client. `HttpTransport` and `Transport` handle
sockets; the tests inject a fake. What you are writing is everything above:
what to send, when to refuse, and how to tell one failure from another.

## Order of attack

Nine test classes, roughly increasing in difficulty. Do them in this order and
each one stands on the last:

| # | class | tests | what it is |
| --- | --- | --- | --- |
| 1 | `TestEndpointGuard` | 4 | paper by default; live needs an explicit opt-in |
| 2 | `TestReads` | 5 | parse account and positions, including a short and a null body |
| 3 | `TestClientOrderId` | 4 | a deterministic id for one intent |
| 4 | `TestRiskLimits` | 5 | ceilings checked before anything is sent |
| 5 | `TestLatestPrice` | 3 | read a trade, refuse a shape you cannot parse |
| 6 | `TestSubmit` | 8 | the order path, including the duplicate |
| 7 | `TestTheNotionalCeiling…` | 6 | the ceiling reaching the real order path |
| 8 | `TestReconcile` | 7 | intended holdings against actual, both directions |
| 9 | `TestWhatA401Says` | 6 | diagnosing a rejected credential |

Classes 1–5 are a day. Class 6 is the exercise. Classes 7–9 are where the
judgement lives.

## The three ideas worth the week

**Idempotency.** `client_order_id` is derived from the rule, the bar and the
direction — never from the clock, never from a random source. A crash between
sending an order and recording the response produces the *same* id on the next
attempt, so the broker rejects the duplicate instead of opening a second
position. `test_is_stable_for_the_same_intent` and `test_ignores_the_time_of_day`
are the two that matter; if you reach for `uuid4()` or `datetime.now()` you
have written the bug this module exists to prevent.

**A duplicate is not an error.** A 422 saying "you already sent this" means a
previous attempt got further than you recorded. The correct response is to look
the order up and return it, because re-sending would double the position.
`test_a_duplicate_id_returns_the_existing_order_instead_of_resending`.

**A limit the caller can skip is not a limit.** The notional ceiling needs a
price. If the caller omits one, fetch it rather than defaulting it away, and if
the fetch fails, *refuse the order* rather than send it unchecked —
`test_an_unpriceable_order_is_refused_rather_than_sent_unchecked`. With one
exception, and it is the sharpest test in the file:
`test_a_retry_is_still_recoverable_when_the_price_lookup_fails`. Work out why
before you read the answer. The hint is that a retry of an order the broker
already holds adds no exposure.

## Rules

1. Do not read the original before you finish.
2. `models.py` is not stubbed; `Side` comes from there.
3. Standard library only — `urllib`, `json`, `hashlib`. No `requests`.
4. `tests/test_live.py` will stay red until this is done. Ignore it; it tests
   `live.py`, which merely holds a broker.

## Hints, in escalating order

1. Build the read paths first (`account`, `positions`, `latest_price`). They
   are pure parsing and they give you a working object to submit orders from.
2. `BrokerOrder` needs to answer three questions — filled, dead, open. The
   module-level `FILLED` and `DEAD` constants in the tests' expectations tell
   you which statuses are terminal.
3. `reconcile` checks the **union** of both sides, not just what you expected.
   A position the broker holds that your run knows nothing about is the more
   dangerous half — nobody is managing it.
4. For `TestWhatA401Says`: the response body is identical for every cause, but
   the key id and the endpoint are both in front of you. Two of the three usual
   causes can be checked rather than guessed. Whitespace first, then the
   paper-key prefix rule, then the fallback.

## Then, and only then

```bash
SHA=$(sed -n 's/^# STUBBED-FROM: //p' src/trading_bot/broker.py)
git show "$SHA:src/trading_bot/broker.py" > /tmp/original_broker.py
diff -u /tmp/original_broker.py src/trading_bot/broker.py
```

## Questions to answer out loud before you call this finished

1. **Find the bug.** The original catches the duplicate-order case with
   `if "422" not in str(exc): raise` — it string-matches a status code out of a
   formatted error message that includes up to 400 characters of the response
   body. Construct the input that makes it wrong. (It exists: a 500 whose body
   happens to contain those three digits, when an order under that client id
   already exists, is reported as a filled order. No test catches it.) Then say
   what the error type should have carried instead, and write the test.
2. `client_order_id` hashes the date, not the timestamp. So two signals for the
   same symbol and side on the same day collide, and the second is treated as a
   duplicate and silently dropped. Is that a bug or the feature? Answer for a
   daily-bar strategy, then answer again for a five-minute one.
3. Live trading requires an explicit opt-in and an unknown host is refused
   outright. Name the specific accident that guard prevents, then say what it
   does *not* prevent.
4. `reconcile` takes a `tolerance` defaulting to `1e-6` and has a test called
   `test_tolerates_float_dust`. Where does dust in a *share count* come from,
   and would you rather fix the tolerance or the representation?
5. `RiskLimits` is a hard stop, not a warning, and the docstring says a rule
   that has never traded live is exactly when a sizing bug is most likely.
   Where should this check live — the broker, the strategy, or somewhere else —
   and what is the argument for each?
6. The 401 handler guesses at a cause and prints it. What is the risk of a
   confidently wrong diagnostic, and how would you word it to get the benefit
   without that risk?
7. Every method raises `BrokerError` for everything: an outage, a bad
   credential, a refused order, an unparseable response. Design the exception
   hierarchy you would actually want, and say which call sites would change.

## After this

The five modules are done and the repo is yours. `git log --author=you` should
now be most of the interesting commits, and you should be able to open any file
at random and defend it.

That is the gate for phase 02 on the roadmap. What follows it — the CLI, the
SQLite migration, the FastAPI service, the deploy — is additive work you build
*on top of* code you understand, which is a different and much easier kind of
hard.
