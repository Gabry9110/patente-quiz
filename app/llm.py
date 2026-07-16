import json
import re
from pathlib import Path

from ollama import Client

from app.config import settings

# Map category slug -> section titles in riassunto-video.md to include as reference.
CATEGORY_REFERENCE_MAP: dict[str, list[str]] = {
    "luci-fari": ["4. Uso dei Fari e Leve al Volante"],
    "dispositivi-obbligatori": ["6. Controllo degli Pneumatici e Lettura della Carta di Circolazione"],
    "pneumatici": ["6. Controllo degli Pneumatici e Lettura della Carta di Circolazione"],
    "spie-comandi": ["2. Quadro Strumenti e Spie Rosse (Grave anomalia – Stop immediato)", "3. Indicatori, Comandi e Pulsanti della Plancia", "7. Specchietto Retrovisore Interno (Leva anti-riflesso)"],
    "oli-livelli": ["5. Controllo del Vano Motore (Cofano)"],
    "regolazioni-postazione": ["1. Regolazioni e Postazione di Guida"],
}


def _load_reference_sections(section_titles: list[str]) -> str:
    """Extract specific ### sections from riassunto-video.md as context."""
    ref_path = settings.project_root / "data" / "riassunto-video.md"
    if not ref_path.exists():
        return ""
    content = ref_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    out: list[str] = []
    capture = False
    for line in lines:
        if line.startswith("### "):
            capture = any(line.lstrip("# ").strip().startswith(t) or t in line for t in section_titles)
            if capture:
                out.append(line)
            continue
        if capture:
            if line.startswith("### ") or line.startswith("## "):
                capture = False
                continue
            out.append(line)
    return "\n".join(out).strip()


SYSTEM_PROMPT = """Sei un esaminatore esperto dell'esame pratico per il conseguimento della patente di guida italiana (categoria B), operante presso una motorizzazione civile o una scuola guida. Conosci a fondo la "fase 1" dell'esame pratico, in cui l'esaminatore pone all'aspirante una serie di domande di teoria e verifica pratica a voce e tramite dimostrazioni sui comandi del veicolo.

Il tuo compito è generare domande a risposta chiusa (multiple choice) di qualità professionale, realistiche e coerenti con quanto un esaminatore chiederebbe davvero durante la fase 1. Le domande devono essere in italiano.

REGOLE RIGOROSE PER LE DOMANDE:
1. Ogni domanda deve avere tra 2 e 4 opzioni di risposta (etichettate implicitamente a, b, c, d).
2. Una o più opzioni possono essere corrette (domande a risposta multipla ammesse quando ha senso).
3. Le opzioni devono essere plausibili: le distrattrici devono essere credibili e non palesemente assurde, per testare la reale comprensione.
4. Per ogni domanda fornisci sempre una breve "explanation" (1-3 frasi) che giustifica la/le risposta/e corretta/e e, se utile, spiega perché le altre sono errate. L'explanation deve essere didattica e utile per il ripasso.
5. Evita domande troppo banali o "trabocchetto" con risposte ovvie. Punta a verificare conoscenze operative concrete (es. procedure di controllo, interpretazione spie, lettura dati tecnici, comportamenti specifici).
6. Mantieni un linguaggio chiaro e tecnico ma accessibile. Usa la terminologia italiana ufficiale (es. "proiettori anabbaglianti", "freno di stazionamento", "Documento Unico di Circolazione", ecc.).
7. Se ti viene fornito del materiale di riferimento (estratto da un riassunto del video dell'istruttore), basa PRIMARIAMENTE le domande su quel contenuto, rispettandone dati, procedure e definizioni. Non contraddirlo. Per i dettagli non coperti dal riferimento usa la tua conoscenza generale del Codice della Strada e delle prassi d'esame.
8. Non inventare norme, valori numerici o procedure. Se non sei sicuro di un dato tecnico specifico (es. pressione di gonfiaggio, soglie specifiche), formula la domanda in modo che la risposta non dipenda da quel dato incerto.
9. Varia lo stile: alcune domande possono chiedere di identificare la procedura corretta, altre di riconoscere il significato di una spia, altre di interpretare una sigla del libretto, altre ancora di selezionare tutte le affermazioni vere.

FORMATO DI OUTPUT OBBLIGATORIO:
Rispondi ESCLUSIVAMENTE con un array JSON valido (nessun testo prima o dopo, nessun markdown code fence). Ogni elemento deve avere esattamente questa forma:
{
  "question": "testo della domanda",
  "explanation": "spiegazione didattica",
  "options": [
    {"text": "testo opzione", "is_correct": true},
    {"text": "testo opzione", "is_correct": false}
  ]
}
L'ordine delle opzioni nell'array sarà l'ordine di visualizzazione (a, b, c, d). Assicurati che almeno una opzione abbia is_correct=true."""


SELF_CHECK_SYSTEM_PROMPT = """Sei un revisore esperto di domande d'esame per la patente italiana (categoria B, fase 1 dell'esame pratico). Ti viene fornita una domanda con le sue opzioni di risposta, la spiegazione fornita dal generatore, e (quando disponibile) un estratto del materiale di riferimento ufficiale (riassunto del video dell'istruttore).

Devi valutare la correttezza tecnica della domanda e delle risposte indicate come corrette, verificando:
- che la/le risposte corrette siano effettivamente corrette alla luce del Codice della Strada, delle norme sui neopatentati e delle procedure d'esame;
- che le distrattrici non siano ambigue o erroneamente corrette;
- che l'explanation non contenga inesattezze;
- se è fornito il riferimento, che la domanda e le risposte siano coerenti con esso (eventualmente segnalando discordanze).

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido (nessun testo prima o dopo, nessun code fence) con questa forma:
{
  "verified": true | false,
  "note": "breve motivazione; se verified=false, indica quale risposta sarebbe corretta o quale inesattezza è stata trovata"
}
Sii severo ma ragionevole: marca verified=true solo se la domanda è tecnicamente corretta e senza ambiguità rilevanti."""


def _client() -> Client:
    return Client(
        host=settings.ollama_host,
        headers={"Authorization": f"Bearer {settings.ollama_api_key}"},
    )


def _extract_json(text: str) -> list | dict | None:
    """Best-effort extraction of a JSON array/object from a model response."""
    text = text.strip()
    # Strip markdown code fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find the outermost array or object.
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _chat(system: str, user: str) -> str:
    resp = _client().chat(
        model=settings.ollama_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        stream=False,
    )
    return resp["message"]["content"]


def generate_questions(category_title: str, category_description: str, reference: str, n: int = 5) -> list[dict]:
    """Ask the LLM for n questions on the given category. Returns list of dicts."""
    user_parts = [
        f"Genera {n} domande a risposta chiusa per la seguente categoria dell'esame pratico (fase 1), patente B:",
        f"\nCATEGORIA: {category_title}",
    ]
    if category_description:
        user_parts.append(f"DESCRIZIONE: {category_description}")
    if reference:
        user_parts.append("\nMATERIALE DI RIFERIMENTO (tratto dal riassunto del video dell'istruttore) — basa su questo le domande quando pertinente:")
        user_parts.append("<<<\n" + reference + "\n>>>")
    user_parts.append(f"\nRestituisci esattamente {n} domande nell'array JSON secondo il formato specificato.")
    user = "\n".join(user_parts)

    raw = _chat(SYSTEM_PROMPT, user)
    parsed = _extract_json(raw)
    if not isinstance(parsed, list):
        raise ValueError(f"LLM did not return a JSON array. Raw: {raw[:500]}")
    cleaned = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        q = item.get("question", "").strip()
        opts = item.get("options", [])
        if not q or not isinstance(opts, list) or len(opts) < 2:
            continue
        clean_opts = []
        any_correct = False
        for o in opts:
            if not isinstance(o, dict):
                continue
            t = (o.get("text") or "").strip()
            if not t:
                continue
            c = bool(o.get("is_correct"))
            any_correct = any_correct or c
            clean_opts.append({"text": t, "is_correct": c})
        if not any_correct or len(clean_opts) < 2:
            continue
        cleaned.append({
            "question": q,
            "explanation": (item.get("explanation") or "").strip(),
            "options": clean_opts,
        })
    return cleaned


def self_check(question: dict, reference: str) -> dict:
    """Run a second LLM pass to verify a question. Returns {verified, note}."""
    user_parts = ["Verifica la seguente domanda d'esame:"]
    user_parts.append(f"\nDOMANDA: {question['question']}")
    user_parts.append("OPZIONI:")
    for i, o in enumerate(question["options"]):
        letter = chr(ord("a") + i)
        flag = " [CORRETTA]" if o["is_correct"] else ""
        user_parts.append(f"  {letter}) {o['text']}{flag}")
    user_parts.append(f"\nSPIEGAZIONE FORNITA: {question.get('explanation','')}")
    if reference:
        user_parts.append("\nRIFERIMENTO UFFICIALE:")
        user_parts.append("<<<\n" + reference + "\n>>>")
    else:
        user_parts.append("\nNessun riferimento specifico disponibile per questa categoria; basati sulla tua conoscenza del Codice della Strada e delle prassi d'esame.")
    user_parts.append("\nRestituisci il JSON con verified e note.")
    user = "\n".join(user_parts)

    raw = _chat(SELF_CHECK_SYSTEM_PROMPT, user)
    parsed = _extract_json(raw)
    if isinstance(parsed, dict) and "verified" in parsed:
        return {"verified": bool(parsed["verified"]), "note": str(parsed.get("note", ""))}
    return {"verified": False, "note": "Verifica automatica non andata a buon fine (output non interpretato)."}


def reference_for_category(slug: str) -> str:
    titles = CATEGORY_REFERENCE_MAP.get(slug, [])
    if not titles:
        return ""
    return _load_reference_sections(titles)