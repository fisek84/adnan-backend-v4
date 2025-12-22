# Handover priručnik

Ovaj folder sadrži sve što je potrebno da ljudi i ChatGPT agenti rade DOSLJEDNO na projektu.

## Šta se ovdje nalazi

- `MASTER_PLAN.md` – glavni plan faza razvoja sistema.
- `CHATGPT_PLAYBOOK.md` – uputstvo kako svaki ChatGPT treba da radi.
- `CHANGELOG_FIXPACK.md` – hronološki zapis većih paketa promjena.
- `tasks/` – pojedinačni task fajlovi (KANON-FIX i ostali zadaci).
- `baseline_test_output.txt` – sačuvani output baseline testova (kad ga napravimo).

## Osnovna pravila

1. Svaka veća promjena ide kroz task fajl u `docs/handover/tasks/`.
2. Jedan task = jedan fokus = jedna git grana = jedan PR.
3. Nakon svake serije promjena moraju proći HAPPY testovi (ili mora biti zapisano da NE prolaze i zašto).
4. Sve bitne informacije za nastavljanje rada idu u sekciju `Progress / Handover` unutar task fajla.
5. ChatGPT i ljudi se uvijek ravnaju prema `MASTER_PLAN.md` i aktivnom tasku.

## Kako početi novi radni ciklus

1. Otvori `MASTER_PLAN.md` i pogledaj koja je faza aktivna.
2. U `docs/handover/tasks/` pronađi odgovarajući task fajl sa `STATUS: IN_PROGRESS`.
3. Pročitaj:
   - `Goal`
   - `Scope`
   - `CANON Constraints`
   - `Progress / Handover`
4. Radi SAMO ono što piše u tom task fajlu. Ako imaš dodatne ideje:
   - upiši ih u `Ideas / Backlog` sekciju tog taska,
   - ne mijenjaj scope usput.

## Testovi kao “gate”

Prije merge-a bilo kakvih većih promjena u glavnu granu, očekuje se da:

- `.\test_runner.ps1`
- `.\test_happy_path.ps1`

budu pokrenuti i rezultat bude zapisan u odgovarajući task fajl i/ili `baseline_test_output.txt`.

Ako nešto pada, to mora biti jasno zabilježeno, i ne smije se ignorisati.
