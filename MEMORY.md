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
