# MEMORY.md — Memoria del Progetto

> Questo file è la **memoria viva** del progetto: storia, decisioni, stato corrente, roadmap e attività aperte.
> Viene aggiornato ad ogni sessione di lavoro significativa.
> Gli agenti AI devono leggerlo prima di qualsiasi attività (vedi `AGENTS.md`).

---

## 📌 Stato del Progetto

- **Nome Progetto**: `oreilly-downloader`
- **Scopo**: Utility Python asincrona per scaricare e ricomporre libri e manuali dalla piattaforma **O'Reilly Learning** (`learning.oreilly.com`) in file `.epub` standard e validi, utilizzabili su qualsiasi e-reader.
- **Stato**: Funzionante / Produzione pronta. Dipendenze minimali (`aiohttp`, `lxml`, `python-dotenv`), estrazione flessibile di ID/URN/URL, concurrency limiting con `asyncio.Semaphore` e suite di test unitari con `pytest`.

---

## 🏛️ Architettura e Funzionamento

Il componente centrale è lo script `oreilly_downloader.py`, strutturato in modo asincrono, modulare e testabile:

```
[CLI User / Env]
    │  (book_id | URN | URL, --jwt | OREILLY_JWT, -o output, -c concurrency)
    ▼
[main()]
    ├─► [extract_book_id()] ──► Normalizza input in ID numerico/stringa
    ├─► [resolve_output_path()] ──► Determina path file di output (.epub o custom dir)
    │
    ▼
[amain()]
    │
    ├─► [check_auth()] ──► GET https://learning.oreilly.com/api/v1/user-preferences/
    │
    └─► [fetch_book()] ──► Inizializza archivio ZIP ({output_file})
            │               - mimetype (application/epub+zip, non compresso)
            │               - META-INF/container.xml
            │
            ├─► GET https://learning.oreilly.com/api/v2/epubs/urn:orm:book:{book_id}/files/
            │   (paginazione automatica con URL 'next')
            │
            └─► [download() con asyncio.Semaphore(concurrency)]
                    │
                    ├─► File binari/asset (.css, .png, .jpg, .svg, .ncx, .opf...)
                    │     └─► Scrittura diretta in EPUB/{full_path}
                    │
                    └─► File di testo/capitoli (.html)
                          ├─► [to_xhtml()]
                          │     - Normalizzazione tag e doctype XHTML
                          │     - Rimozione prefisso API dai percorsi relativi ('href', 'src')
                          │     - Wrapping in <html xmlns="http://www.w3.org/1999/xhtml"> se incompleto
                          │     - Generazione tag <head><title> da <h1>
                          └─► Scrittura in EPUB/{full_path}
```

### Dettaglio Componenti e Funzioni
1. **`main()` / `amain()`**: Entrypoint CLI e runner asincrono. Gestisce il cleanup automatico del file parziale in caso di errori fatali.
2. **`extract_book_id(val)`**: Parser di input flessibile che accetta ID numerici, ISBN, formato URN (`urn:orm:book:...`) e URL completi della piattaforma O'Reilly.
3. **`resolve_output_path(output_arg, book_id)`**: Risolve il path di destinazione gestendo file specifici, directory esistenti o la directory corrente.
4. **`check_auth(session)`**: Verifica la validità del cookie JWT interrogando `/api/v1/user-preferences/`.
5. **`fetch_book(book_id, zfh, session, concurrency)`**:
   - Predispone la struttura standard EPUB conforme OEBPS (`mimetype`, `META-INF/container.xml`).
   - Cicla sulle pagine dell'API O'Reilly scaricando la lista dei file costituenti il libro.
   - Esegue il download asincrono controllato da `asyncio.Semaphore` per prevenire rate-limiting (HTTP 429).
6. **`to_xhtml(s, root_path)`**: Converte l'HTML in XHTML valido con namespace OEBPS e ripulisce gli attributi `src` e `href` per renderli relativi all'archivio EPUB.

---

## 🧭 Decisioni Architetturali (ADR)

| Decisione | Scelta | Motivazione |
|---|---|---|
| **Libreria HTTP Asincrona** | `aiohttp` | Permette download concorrente ad alte prestazioni di centinaia di asset e capitoli per singolo libro. Gestione SSL nativa standard. |
| **Parsing XML/HTML** | `lxml` (`lxml.html`, `lxml.etree`) | Velocità elevata in C e supporto completo per la manipolazione XML/XHTML con namespace. |
| **Packaging EPUB** | `zipfile` (libreria standard) | L'EPUB è formalmente uno zip con struttura specifica (`mimetype` come primo file non compresso `ZIP_STORED`). Nessuna libreria esterna pesante richiesta. |
| **Gestione Configurazione** | `python-dotenv` + `os.getenv("OREILLY_JWT")` | Permette di non esporre il JWT nella cronologia bash e semplifica l'uso da script automatizzati. |
| **Gestione Dipendenze** | `uv` / `pyproject.toml` | Velocità di installazione, isolamento garantito e compatibilità standard PEP 518/PEP 621. |

---

## 🎯 Roadmap e Potenziali Miglioramenti Futuri

1. **Barra di Avanzamento (Progress Bar)**:
   - Integrazione opzionale di un indicatore visivo di avanzamento a terminale (es. `rich` o `tqdm`).
2. **Estrazione Metadati & Titolo nel Nome File**:
   - Possibilità di interrogare i metadati del libro dall'API per nominare automaticamente il file con Titolo e Autore (es. `Fluent_Python_2nd_Edition.epub`).
3. **Validazione EPUB Automatizzata**:
   - Possibilità di lanciare `epubcheck` come step opzionale di verifica post-generazione.

---

## ⚠️ Problemi Noti e Soluzioni

| Problema | Causa | Soluzione |
|---|---|---|
| Download incompleto o capitoli troncati | Cookie JWT assente, non valido o account privo di abbonamento attivo | Fornire un token JWT valido estratto dal browser (cookie `orm-jwt`) tramite `--jwt`, variabile `OREILLY_JWT` o file `.env`. |
| `Warning: Authentication failed` / HTTP 403 su user-preferences | Protezione WAF/Akamai di O'Reilly che blocca lo User-Agent di default di `aiohttp` | Configurazione di `DEFAULT_HEADERS` realistici (`User-Agent`, `Accept`, `Referer`) nella `ClientSession`. |
| `AttributeError: 'NoneType' object has no attribute 'startswith'` | Nodi di commento (`HtmlComment`) o attributi booleani durante `to_xhtml()` | Controllo esplicito su `val and isinstance(val, str) and val.startswith(...)` in `to_xhtml()`. |
| Immagini o link interni non visualizzati | Percorsi assoluti dell'API non rimossi | La funzione `to_xhtml()` rimuove il prefisso `root_path` convertendoli in percorsi relativi interni all'archivio EPUB. |
| Rate limiting (HTTP 429) su libri enormi | Troppe richieste simultanee verso il server | Concorrenza limitata e configurabile con `asyncio.Semaphore` (default: 10). |

---

## 📜 Log delle Sessioni

### Sessione 1 - Analisi Iniziale, Setup e Revisione Progetto (2026-08-25)
- **Attività**:
  - Analisi approfondita di `oreilly_downloader.py`, dipendenze e flusso operativo.
  - Pulizia e rettifica del file `pyproject.toml` (dipendenze minimali ed essenziali: `aiohttp`, `lxml`, `python-dotenv`, `pytest`, `pytest-asyncio`, `ruff`).
  - Configurazione di `ruff.toml` con target Python 3.12 e rimozione di configurazioni non pertinenti.
  - Riscrittura e arricchimento di `oreilly_downloader.py`:
    - Supporto per estrazione automatica di ID da URL completi O'Reilly, URN o ISBN (`extract_book_id`).
    - Gestione opzione `-o / --output` per specificare file o directory (`resolve_output_path`).
    - Supporto per variabile d'ambiente `OREILLY_JWT` e caricamento automatico da `.env` con `python-dotenv`.
    - Limitazione della concorrenza tramite `asyncio.Semaphore` con parametro `-c / --concurrency`.
    - Gestione pulita degli errori HTTP e rimozione file corrotti/parziali in caso di fallimento.
  - Creazione suite di test unitari in `tests/test_downloader.py` (5 test passati al 100%).
  - Aggiornamento di `.gitignore` per escludere `*.epub`.
  - Redazione completa di `AGENTS.md` e `MEMORY.md`.

### Sessione 2 - Centralizzazione Token (.env/CLI), Diagnostica Scadenza JWT e Suite di Test (2026-08-25)
- **Attività**:
  - Centralizzazione della gestione del token di autenticazione:
    - Lettura delle variabili d'ambiente esclusivamente dal file `.env` (tramite `load_dotenv()`).
    - Creazione di `resolve_jwt(cli_jwt)`: dà precedenza a `--jwt` su `OREILLY_JWT` in `.env`, ripulisce spazi, apici e prefissi `Bearer `.
    - Creazione di `get_jwt_expiration(token)`: decodifica il payload JWT per individuare e segnalare con precisione la scadenza (`exp`) prima o durante le richieste.
    - Creazione di `get_auth_config(jwt)`: assembla in modo univoco `headers` (`DEFAULT_HEADERS` + `Authorization: Bearer <jwt>`) e `cookies` (`orm-jwt: <jwt>`).
  - Risoluzione del falso avviso e diagnosi autenticazione:
    - Identificata scadenza temporale effettiva del token nel payload (`exp`).
    - Introdotti `DEFAULT_HEADERS` per superare i blocchi bot/WAF (Akamai 403).
  - Risolto bug `AttributeError: 'NoneType' object has no attribute 'startswith'` in `to_xhtml()` per nodi `HtmlComment` e attributi non-string.
  - Aggiornata e ampliata la suite di test in `tests/test_downloader.py` a **15 test unitari e di integrazione**:
    - Precedenza e pulizia token con `resolve_jwt`.
    - Estrazione timestamp scadenza con `get_jwt_expiration`.
    - Configurazione coerente di header e cookie con `get_auth_config`.
    - Test live `test_live_auth_from_env` con skip controllato se il token in `.env` è assente o scaduto.
  - Esecuzione e verifica linting (`ruff check`) e formattazione (`ruff format`).

### Sessione 3 - Fix Token Stale da Ambiente e Verifica End-to-End (2026-08-25)
- **Attività**:
  - Risolto problema del token ignorato: lo script usava una variabile `OREILLY_JWT` ancora esportata nella shell (scaduta) perché `load_dotenv()` di default non sovrascrive le variabili d'ambiente esistenti.
  - Cambiato il caricamento in `load_dotenv(override=True)` in `oreilly_downloader.py` e nel test live: ora il file `.env` è la fonte autorevole e prevale su eventuali export stale nella shell (allineato alla priorità documentata in README: `--jwt` → `.env`).
  - Identificato e verificato un book ID errato: `978163343453` (12 cifre, incompleto) restituiva `count: 0`; l'ISBN-13 corretto `9781633434530` restituisce 144 file dall'API.
  - Suite di test: **15 passati al 100%** (`uv run pytest`), incluso il test live di autenticazione con il token valido del `.env`.

### Sessione 4 - Auto-Correzione ISBN-13 e Avviso 0 File (2026-08-25)
- **Attività**:
  - Aggiunta `isbn13_check_digit(prefix)`: calcola la cifra di controllo ISBN-13 per un prefisso a 12 cifre.
  - Aggiunta `normalize_book_id(raw_id)`: estrae l'ID e corregge automaticamente i prefissi ISBN-13 a 12 cifre (regex `97[89]\d{9}`) aggiungendo la cifra di controllo mancante, con nota a console.
  - Aggiunto avviso in `fetch_book()` quando un libro restituisce 0 file (ID errato o libro non disponibile).
  - Verifica end-to-end: `978163343453` viene corretto in `9781633434530`, download di 144 file e creazione di un EPUB valido (mimetype primo e non compresso, struttura EPUB/Text, toc.ncx).
  - Suite di test portata a **17 test passati al 100%** (`uv run pytest`), lint e format ok (`ruff`).

### Sessione 5 - Fix Percorsi Risorse nelle Sottocartelle (EPUB) (2026-08-25)
- **Attività**:
  - Risolto il problema delle immagini non visibili nell'EPUB: le risorse venivano referenziate come `Images/x.png` (relative alla radice EPUB) ma gli HTML vivono in `EPUB/Text/`, quindi i percorsi dovevano includere `../`.
  - `to_xhtml()` ora accetta `dest_path` (es. `Text/chapter-1.html`) e riscrive i riferimenti assoluti API con `posixpath.relpath()` rispetto alla directory di destinazione (es. `../Images/x.png`, link tra capitoli `ch02.html`).
  - `fetch_book()` ora processa anche i file `.xhtml` (prima solo `.html`): la copertina `Text/titlepage.xhtml` non era convertita e conteneva il percorso API assoluto rotto.
  - Verifica end-to-end: EPUB rigenerato con `../Images/...` corretti, zero percorsi API assoluti residui e **0 riferimenti rotti** (ogni src/href risolve a un file esistente nell'archivio).
  - Suite di test portata a **19 test passati al 100%** (`uv run pytest`), lint e format ok (`ruff`).
