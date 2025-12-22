# CHATGPT PLAYBOOK

Ovaj dokument objašnjava kako bilo koji ChatGPT treba da radi na ovom projektu.

## 1. Šta ChatGPT MORA pročitati prije rada

Svaki ChatGPT, prije bilo kakvog savjeta ili izmjene koda, treba da pročita:

- `docs/handover/MASTER_PLAN.md`
- `docs/handover/README.md`
- aktivni task fajl iz `docs/handover/tasks/` (onaj sa `STATUS: IN_PROGRESS`)

## 2. Kako ChatGPT bira AKTIVNI task

1. Otvori folder `docs/handover/tasks/`.
2. Pronađi fajl koji u vrhu ima liniju `STATUS: IN_PROGRESS`.
3. Ako postoji više takvih fajlova:
   - izaberi onaj sa najnovijim unosom u sekciji `Progress / Handover`.
4. Radi SAMO na tom task fajlu. Ne otvaraj nove teme i ne mijenjaj fokus.

## 3. Pravila ponašanja za ChatGPT

- Poštuj CANON pravila iz `MASTER_PLAN.md`.
- Ne uvodi nove feature-e ili refaktore koji NISU u sekciji `Scope (In scope)` aktivnog taska.
- Ako uočiš dobru ideju koja je van scope-a:
  - zapiši je u sekciju `Ideas / Backlog` unutar tog task fajla,
  - NE implementiraj je u ovom tasku.

## 4. Kako izgleda jedna ChatGPT sesija

Za svaki radni blok, ChatGPT treba da uradi sljedeće:

1. Pročitati u aktivnom task fajlu sekcije:
   - `Goal`
   - `Scope`
   - `CANON Constraints`
   - `Progress / Handover`
2. Napisati mini-plan za ovaj radni blok:
   - 1 do 3 konkretna koraka koje ćemo uraditi sada.
3. Predložiti izmjene:
   - koje fajlove treba mijenjati,
   - koji dio koda dodati/izmijeniti/obrisati,
   - koje komande pokrenuti (git, testovi).
4. Nakon što korisnik primijeni promjene i pokrene testove:
   - ChatGPT treba tražiti da korisnik ručno ažurira sekciju `Progress / Handover` u task fajlu:
     - šta je urađeno,
     - koji testovi su pokrenuti,
     - rezultat testova,
     - preporučeni sljedeći koraci.

## 5. Kako se završava jedan task

Task je ZAVRŠEN tek kada:

1. Svi navedeni testovi u sekciji `Tests to run` prolaze.
2. `Acceptance criteria` sekcija task fajla je ispunjena.
3. STATUS u task fajlu je promijenjen u `STATUS: DONE`.
4. Dodat je zapis u `docs/handover/CHANGELOG_FIXPACK.md` za taj task.

## 6. Šta ChatGPT NE SMIJE raditi

- Ne smije mijenjati scope taska “usput”.
- Ne smije raditi više taskova paralelno.
- Ne smije uvoditi nove write putanje mimo CANON pravila (centralna Write Gateway).
- Ne smije brisati postojeću logiku bez jasnog razloga u task fajlu i bez Happy testova.
