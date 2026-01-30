# Audit: CEO Advisor identity replaced by fallback (gateway leak-guard)

## 1) Očekivano ponašanje
- Kada korisnik postavi identity/meta pitanje o asistentu (npr. “Ko si”, “Koja je tvoja uloga u sistemu”, “What is your role”), sistem treba da vrati kanonski identity odgovor CEO Advisor-a (read-only) i da ga isporuči korisniku bez zamjene fallback-om.

## 2) Stvarno ponašanje (prije hotfix-a)
- CEO Advisor deterministički generiše kanonski identity tekst (počinje sa “Ja sam CEO Advisor…”), ali gateway leak-guard ga prepoznaje kao „interni intro template“ i sanitizuje izlaz u generički read-only fallback tekst, osim ako prompt nije na striktnoj allowlist-i.

## 3) Root-cause (tačno gdje se dešava zamjena)
- Detekcija „internog CEO intro template“:
  - `gateway/gateway_server.py` (oko linije 2274): `_INTERNAL_CEO_INTRO_TEMPLATE_MARKERS` — marker “Ja sam CEO Advisor u ovom workspace-u”.
  - `gateway/gateway_server.py` (oko linije 2386): `_looks_like_internal_ceo_intro_template` — tretira tekst kao template čim sadrži marker intro linije.
- Sanitizacija (zamjena) user-visible teksta:
  - `gateway/gateway_server.py` (oko linije 2402): `sanitize_user_visible_answer` — kada `is_intro_tpl=True` i prompt nije na `_user_explicitly_asked_identity_or_howto` (oko linije 2307), funkcija zamijeni `out["text"]` sa `_safe_replacement_text_for_prompt(prompt)` i skloni original u `metadata.debug.internal_system_text`.
- Problem: identity pitanje “Koja je tvoja uloga u sistemu” nije bilo prepoznato kao „explicit identity/how-to prompt“ u `_user_explicitly_asked_identity_or_howto`, pa je gateway sanitizovao kanonski identity odgovor.

## Hotfix pristup (minimalno, bez širenja allowlist-a po frazama)
- U `gateway/gateway_server.py` dodan je mali bypass u `sanitize_user_visible_answer`:
  - Bypass je striktan: radi samo kada je `agent_id == "ceo_advisor"` i `trace.intent == "assistant_identity"`.
  - Alternativno, podržan je eksplicitan server-side flag `trace.canonical_identity == True` (ako se ikad uvede).
- Ovo rješava regresiju bez dodavanja novih fraza u allowlist prompt-match.
