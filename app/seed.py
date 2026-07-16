import re
import sys
import time

from sqlmodel import Session, select

from app.db import engine, init_db
from app.llm import generate_questions, reference_for_category, self_check
from app.models import Category, Option, Question


# Seed categories derived from data/lista-argomenti.md.
# slug -> (title, description, has_reference)
CATEGORIES = [
    ("documenti-circolazione", "Documenti necessari per la circolazione", "Patente, assicurazione e carta di circolazione: cosa serve, quando, validità e obblighi.", False),
    ("veicoli-patente-b", "Veicoli che si possono guidare con la patente B", "Limiti di massa, categorie di veicoli conducibili con la patente B e relative eccezioni.", False),
    ("carta-circolazione", "Carta di Circolazione (Documento Unico)", "Dati amministrativi e tecnici contenuti nel DU; lettura dei dati tecnici degli pneumatici.", True),
    ("immatricolazione-revisione", "Immatricolazione e Revisione", "Procedure di immatricolazione, obblighi e cadenze di revisione del veicolo.", False),
    ("luci-fari", "Luci in dotazione e uso dei fari", "Proiettori anabbaglianti, abbaglianti, fendinebbia, retronebbia: quando sono obbligatori e come si usano.", True),
    ("dispositivi-obbligatori", "Dispositivi obbligatori a bordo", "Gilet ad alta visibilità, segnale mobile di pericolo (triangolo), estintore, cassetta di pronto soccorso: obblighi e utilizzo.", True),
    ("neopatentati", "Limiti e normative per neopatentati", "Limiti di velocità e potenza, decurtazione punti, tasso alcolico, altre restrizioni per i neopatentati.", False),
    ("pneumatici", "Controllo visivo degli pneumatici", "Pressione di gonfiaggio, usura del battistrada, testimoni d'usura, integrità del fianco, lettura della sigla.", True),
    ("spie-comandi", "Spie e comandi interni", "Significato delle spie rosse (azione da intraprendere durante la marcia) e uso dei comandi: tergicristalli, sbrinamento, ricircolo, frecce, quattro frecce, start&stop.", True),
    ("oli-livelli", "Controllo dei livelli: olio motore e liquido refrigerante", "Procedura di controllo dell'olio motore (asta, MIN/MAX, motore freddo, auto in piano) e del liquido di raffreddamento (vaschetta di espansione, sicurezza motore caldo).", True),
]

QUESTIONS_PER_CATEGORY = 10


def parse_list_argomenti() -> list[tuple[str, str]]:
    """Fallback: parse the md file to titles (unused now, kept for reference)."""
    path = "data/lista-argomenti.md"
    out = []
    try:
        for line in open(path, encoding="utf-8"):
            m = re.match(r"\d+\.\s+(.*)", line.strip())
            if m:
                out.append((m.group(1).rstrip(";"), ""))
    except FileNotFoundError:
        pass
    return out


def seed_categories(session: Session) -> dict[str, Category]:
    cats: dict[str, Category] = {}
    for i, (slug, title, desc, has_ref) in enumerate(CATEGORIES):
        existing = session.exec(select(Category).where(Category.slug == slug)).first()
        if existing:
            existing.title = title
            existing.description = desc
            existing.has_reference = has_ref
            existing.order = i
            session.add(existing)
            cats[slug] = existing
        else:
            c = Category(slug=slug, title=title, description=desc, has_reference=has_ref, order=i)
            session.add(c)
            session.flush()
            cats[slug] = c
    session.commit()
    return cats


def seed_questions(session: Session, cats: dict[str, Category], do_self_check: bool = True) -> None:
    for slug, cat in cats.items():
        existing_count = session.exec(
            select(Question).where(Question.category_id == cat.id)
        ).all()
        if len(existing_count) >= QUESTIONS_PER_CATEGORY:
            print(f"  [{slug}] already has {len(existing_count)} questions, skipping.")
            continue

        needed = QUESTIONS_PER_CATEGORY - len(existing_count)
        print(f"  [{slug}] generating {needed} questions...")
        ref = reference_for_category(slug)
        try:
            generated = generate_questions(cat.title, cat.description, ref, n=needed)
        except Exception as e:
            print(f"    ! generation failed: {e}")
            continue

        for qd in generated:
            q = Question(
                category_id=cat.id,
                text=qd["question"],
                explanation=qd.get("explanation", ""),
                source="seed",
            )
            if do_self_check:
                try:
                    res = self_check(qd, ref)
                    q.verified = res["verified"]
                    q.verification_note = res["note"]
                except Exception as e:
                    q.verified = False
                    q.verification_note = f"self-check error: {e}"
            session.add(q)
            session.flush()
            for pos, od in enumerate(qd["options"]):
                session.add(Option(
                    question_id=q.id,
                    text=od["text"],
                    is_correct=od["is_correct"],
                    position=pos,
                ))
        session.commit()
        print(f"    + added {len(generated)} questions.")
        time.sleep(1)  # be gentle with the API


def main() -> int:
    print("Initialising database tables...")
    init_db()
    with Session(engine) as session:
        print("Seeding categories...")
        cats = seed_categories(session)
        do_selfcheck = "--no-selfcheck" not in sys.argv
        print(f"Seeding questions (self_check={do_selfcheck})...")
        seed_questions(session, cats, do_self_check=do_selfcheck)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())