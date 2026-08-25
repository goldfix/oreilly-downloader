# AGENTS.md — Istruzioni per Agenti AI

> Questo file è rivolto agli assistenti AI (es. Claude, Gemini, Codex) che lavorano su questo progetto.
> Leggi sempre questo file prima di iniziare qualsiasi attività.

---

## 📖 Prima di tutto: leggi MEMORY.md

**`MEMORY.md`** è la memoria principale del progetto. Contiene:
- Stato attuale del progetto (cosa è completato, cosa è in corso, cosa è aperto)
- Architettura dettagliata e flusso dati
- Decisioni architetturali già prese e la loro motivazione
- Roadmap e attività aperte
- Log delle sessioni di lavoro significative
- Tabella dei problemi noti e le relative soluzioni

**Non procedere su nessuna attività senza aver letto `MEMORY.md`** — eviterai di rifare lavoro già fatto o di introdurre regressioni.

---

## 🗺️ Struttura del Progetto

```
oreilly-downloader/
├── AGENTS.md                  # Istruzioni operative e regole per Agenti AI (questo file)
├── MEMORY.md                  # Memoria viva, stato, decisioni e roadmap ← LEGGI SEMPRE
├── README.md                  # Documentazione pubblica e guida all'uso (English)
├── LICENSE                    # Licenza del progetto
├── oreilly_downloader.py      # Script principale di download asincrono e packaging EPUB
├── pyproject.toml             # Configurazione del progetto e dipendenze uv / PEP 518
├── ruff.toml                  # Configurazione linter e formatter Ruff
├── py_env.sh                  # Helper script per gestione e attivazione virtualenv con uv
├── py_var.sh                  # Variabili d'ambiente locali (NON committare)
├── tests/                     # Test unitari e di regressione
│   └── test_downloader.py    # Test parsing URL/ID, conversione XHTML, container EPUB
└── .gitignore                 # File e cartelle esclusi dal version control
```

---

## ⚙️ Regole di Codice

### Lingua
- **Python** (commenti `#`, docstring `"""`): **inglese** — standard di sviluppo
- **Messaggi di log e CLI**: **inglese**
- **Documentazione operativa interna (AGENTS.md, MEMORY.md)**: **italiano**

### Qualità del Codice
- Mantenere l'implementazione **semplice, robusta, modulare e leggibile**.
- Non introdurre dipendenze non necessarie; privilegiare la libreria standard o librerie consolidate (`aiohttp`, `lxml`, `python-dotenv`).
- Gestire sempre correttamente le eccezioni di rete e i casi limite (token JWT mancante/scaduto, rate limiting, file mancanti o corrotti).
- Utilizzare type hints (Python 3.11+) e mantenere il codice formattato e conforme alle regole di `ruff`.

### Sicurezza e Privacy
- **Non committare MAI token JWT, cookie, chiavi o file `.epub`** (il file `.gitignore` include già `*.epub`, `.env`, `py_var.sh`).
- Verificare sempre lo stato di `git status` prima di qualsiasi commit.

---

## 🔑 Comandi Essenziali

```bash
# Attivare l'ambiente virtuale
source py_env.sh active

# Inizializzare / sincronizzare l'ambiente con uv (Python 3.12)
source py_env.sh init 3.12

# Eseguire il downloader (accetta ID, URN o URL completo O'Reilly)
python oreilly_downloader.py <BOOK_ID_OR_URL> [--jwt 'ORM_JWT_TOKEN'] [-o OUTPUT_PATH] [-c CONCURRENCY]

# Eseguire i test con pytest
uv run pytest

# Verifica linting con Ruff
uv run ruff check .

# Formattazione con Ruff
uv run ruff format .
```

---

## ✅ Checklist Prima di un Commit

1. Esegui `uv run pytest` per verificare che tutti i test passino.
2. Esegui `uv run ruff check .` per verificare assenza di errori di linting.
3. Esegui `uv run ruff format .` per la formattazione coerente del codice.
4. Assicurati che non siano inclusi token, cookie, chiavi private o file `.epub` (`git status`).
5. Aggiorna `MEMORY.md` nella sezione *Log delle Sessioni* descrivendo le modifiche apportate.
