import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from app.browser.distiller import Element, Snapshot
from app.llm.client import LLM, ProviderUnavailable
from app.models.schemas import Brief, FieldSpec, Option, Receipt, TaskSchema


def normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold().replace("_", " "), flags=re.UNICODE))


def phrase(text: str) -> str:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", text).replace("_", " ").replace("-", " ")
    return spaced[:1].upper() + spaced[1:]


# Semantic vocabulary for common form fields. Exact website labels remain visible in the interface.
CONCEPTS = [
    (r"\b(co applicant|joint applicant|secondary applicant)\b.*\b(e.?mail)\b", ("Co-applicant email", "सह-आवेदक का ईमेल", "ಸಹ ಅರ್ಜಿದಾರರ ಇಮೇಲ್", "Correo del cosolicitante", "E-mail du co-demandeur"), "Enter the other applicant’s email address."),
    (r"\b(co applicant|joint applicant|secondary applicant)\b.*\bname\b", ("Co-applicant’s name", "सह-आवेदक का नाम", "ಸಹ ಅರ್ಜಿದಾರರ ಹೆಸರು", "Nombre del cosolicitante", "Nom du co-demandeur"), "Use the other applicant’s full name."),
    (r"\b(full name|legal name|applicant name)\b|^name$", ("Full name", "पूरा नाम", "ಪೂರ್ಣ ಹೆಸರು", "Nombre completo", "Nom complet"), "Use your full name as it appears on official documents."),
    (r"\b(first name|given name|forename)\b", ("First name", "पहला नाम", "ಮೊದಲ ಹೆಸರು", "Nombre", "Prénom"), "Enter your given name."),
    (r"\b(last name|family name|surname)\b", ("Last name", "उपनाम", "ಉಪನಾಮ", "Apellido", "Nom de famille"), "Enter your family name."),
    (r"\b(email|e mail|electronic address)\b", ("Email address", "ईमेल पता", "ಇಮೇಲ್ ವಿಳಾಸ", "Correo electrónico", "Adresse e-mail"), "Enter an address where you can receive messages."),
    (r"\b(phone|tel|telephonic|telephone|mobile number)\b", ("Phone number", "फ़ोन नंबर", "ದೂರವಾಣಿ ಸಂಖ್ಯೆ", "Número de teléfono", "Numéro de téléphone"), "Include the country code if the site requests it."),
    (r"\b(date of birth|birth date|bday|dob)\b", ("Date of birth", "जन्मतिथि", "ಜನ್ಮ ದಿನಾಂಕ", "Fecha de nacimiento", "Date de naissance"), "Enter the date shown on your identity document."),
    (r"\b(country|domicile|jurisdiction of residence)\b", ("Country of residence", "निवास का देश", "ವಾಸಿಸುವ ದೇಶ", "País de residencia", "Pays de résidence"), "Choose the country where you legally live."),
    (r"\b(tax cadence|tax frequency|filing frequency)\b", ("How often do you file taxes?", "आप कितनी बार कर विवरणी भरते हैं?", "ನೀವು ಎಷ್ಟು ಬಾರಿ ತೆರಿಗೆ ರಿಟರ್ನ್ ಸಲ್ಲಿಸುತ್ತೀರಿ?", "¿Con qué frecuencia declaras impuestos?", "À quelle fréquence déclarez-vous vos impôts ?"), "Choose the filing schedule that applies to you."),
    (r"\b(applicant classification|applicant type|entity type)\b", ("What type of applicant are you?", "आप किस प्रकार के आवेदक हैं?", "ನೀವು ಯಾವ ರೀತಿಯ ಅರ್ಜಿದಾರರು?", "¿Qué tipo de solicitante eres?", "Quel type de demandeur êtes-vous ?"), "Choose the category that best describes this application."),
    (r"\b(project url|github|website url)\b", ("Project link", "प्रोजेक्ट लिंक", "ಯೋಜನೆಯ ಲಿಂಕ್", "Enlace del proyecto", "Lien du projet"), "Enter a public link beginning with https://."),
    (r"\b(annual revenue|revenue bracket)\b", ("Annual revenue range", "वार्षिक आय की सीमा", "ವಾರ್ಷಿಕ ಆದಾಯದ ಶ್ರೇಣಿ", "Rango de ingresos anuales", "Tranche de chiffre d’affaires annuel"), "Choose the range for the business’s yearly revenue."),
    (r"\b(delivery|transmittal|contact method)\b", ("How should the site contact you?", "साइट आपसे कैसे संपर्क करे?", "ಸೈಟ್ ನಿಮ್ಮನ್ನು ಹೇಗೆ ಸಂಪರ್ಕಿಸಬೇಕು?", "¿Cómo debe contactarte el sitio?", "Comment le site doit-il vous contacter ?"), "Choose how you want to receive updates."),
    (r"\b(project proposal|proposal|supporting document|attachment)\b", ("Upload a supporting document", "सहायक दस्तावेज़ अपलोड करें", "ಪೂರಕ ದಾಖಲೆ ಅಪ್‌ಲೋಡ್ ಮಾಡಿ", "Sube un documento de respaldo", "Ajoutez un justificatif"), "Use the file types listed by the website."),
]
LANGUAGES = {"en": 0, "hi": 1, "kn": 2, "es": 3, "fr": 4}
GENERIC_HINT = {
    "en": {"check": "Read the statement and confirm it only if it applies.", "choice": "Choose an option accepted by the website.", "text": "Enter the information requested by the website."},
    "hi": {"check": "कथन पढ़ें और लागू होने पर ही पुष्टि करें।", "choice": "वेबसाइट का एक विकल्प चुनें।", "text": "वेबसाइट द्वारा माँगी गई जानकारी दर्ज करें।"},
    "kn": {"check": "ಹೇಳಿಕೆಯನ್ನು ಓದಿ ಮತ್ತು ಅನ್ವಯಿಸಿದರೆ ಮಾತ್ರ ದೃಢೀಕರಿಸಿ.", "choice": "ವೆಬ್‌ಸೈಟ್‌ನ ಆಯ್ಕೆಯನ್ನು ಆರಿಸಿ.", "text": "ವೆಬ್‌ಸೈಟ್ ಕೇಳಿರುವ ಮಾಹಿತಿಯನ್ನು ನಮೂದಿಸಿ."},
    "es": {"check": "Lee la declaración y confírmala si se aplica.", "choice": "Elige una opción del sitio web.", "text": "Introduce la información que solicita el sitio web."},
    "fr": {"check": "Lisez la déclaration et confirmez si elle s’applique.", "choice": "Choisissez une option proposée par le site.", "text": "Saisissez les informations demandées par le site."},
}


def display(original: str, kind: str, help_text: str, language: str):
    category = "check" if kind == "checkbox" else "choice" if kind in {"select", "radio", "combobox"} else "text"
    hint = GENERIC_HINT[language][category]
    for pattern, labels, explanation in CONCEPTS:
        if kind != "checkbox" and re.search(pattern, normalize(original)):
            return labels[LANGUAGES[language]], (help_text or explanation) if language == "en" else hint
    return phrase(original), (help_text or hint) if language == "en" else hint


@dataclass
class Target:
    spec: FieldSpec
    elements: list[Element]

    @property
    def element(self):
        return self.elements[0]


def field_kind(e: Element) -> str:
    tag, input_type, role = e["tag"], e["type"], e["role"]
    if e["disabled"] or e["readonly"]:
        return ""
    if tag == "select":
        return "select"
    if role in {"combobox", "listbox"}:
        return "combobox"
    if role in {"radio", "checkbox"}:
        return role
    if tag == "textarea":
        return "textarea"
    if tag == "input" and input_type not in {"button", "submit", "reset", "image", "hidden", "password"}:
        return input_type or "text"
    if role == "textbox" or tag not in {"a", "button"} and role != "button" and not input_type:
        return "text"
    return ""


def field_targets(snapshot: Snapshot, language: str) -> list[Target]:
    groups: dict[tuple, list[Element]] = {}
    for e in snapshot.elements:
        kind = field_kind(e)
        if not kind:
            continue
        if kind == "radio" and (e["name"] or e["legend"]):
            identity = (e.scope, e["form_key"], kind, e["name"] or e["legend"])
        else:
            identity = (e.scope, e["form_key"], kind, e["name"], e["id"], normalize(e.label))
            if identity in groups:
                identity += (e["wm_id"],)
        groups.setdefault(identity, []).append(e)

    targets = []
    path = urlsplit(snapshot.url).path
    for identity, elements in groups.items():
        e = elements[0]
        kind = identity[2]
        original = (e["legend"] or phrase(e["name"])) if kind == "radio" and (e["legend"] or e["name"]) else e.label
        original = original or "Unlabeled input"
        label, hint = display(original, kind, e["nearby_help_text"], language)
        key = hashlib.sha256(repr((path, identity, normalize(original))).encode()).hexdigest()[:24]
        options = [Option(label=item["label"], value=item["value"]) for item in e["options"] if not item["disabled"] and item["value"]]
        if kind == "radio" and not options:
            options = [Option(label=item.label, value=item["current_value"] or item.label) for item in elements]
        current = e["current_value"]
        if kind == "radio":
            current = next((item["current_value"] or item.label for item in elements if item["checked"]), "")
        elif kind == "checkbox":
            current = e["checked"]
        elif kind == "combobox" and options:
            match = next((item for item in options if normalize(item.label) == normalize(str(current))), None)
            if match:
                current = match.value
        targets.append(Target(FieldSpec(
            key=key, original=original, label=label, hint=hint, kind=kind,
            required=any(item["required"] for item in elements), options=options, current=current,
            accept=e["accept"], multiple=e["multiple"], error=e["validation"] or None,
            minimum=e["minimum"], maximum=e["maximum"], pattern=e["pattern"], max_length=e["maxlength"], step=e["step"],
        ), elements))
    return targets


class Rewrite(BaseModel):
    key: str
    label: str = Field(max_length=160)
    hint: str = Field(max_length=400)


class Analysis(BaseModel):
    summary: str = Field(max_length=1200)
    documents: list[str] = Field(max_length=12)
    deadlines: list[str] = Field(max_length=12)
    warnings: list[str] = Field(max_length=12)
    eligibility: list[str] = Field(max_length=12)
    fields: list[Rewrite] = Field(max_length=100)


def heuristic_brief(snapshot: Snapshot) -> Brief:
    lines = [
        sentence.strip() for line in snapshot.notices.splitlines()
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line) if sentence.strip()
    ]

    def matches(pattern):
        return list(dict.fromkeys(line for line in lines if re.search(pattern, line, re.I)))[:5]

    return Brief(
        summary=snapshot.headings[0] if snapshot.headings else snapshot.title or "Website form",
        documents=matches(r"\b(?:document|proposal|pdf|attachment|upload|supporting evidence)\b"),
        deadlines=matches(r"\b(?:deadline|closes?|no later than|due date|apply by|submit by)\b"),
        warnings=matches(r"\b(?:warning|non-refundable|permanent|penalty|cannot be|non-transferable)\b"),
        eligibility=matches(r"\b(?:eligib\w*|applicants? must|only applicants|participating|minimum age)\b"),
    )


async def analyze(llm: LLM, snapshot: Snapshot, targets: list[Target], goal: str, language: str, *, include_brief=True):
    try:
        analysis = await llm.ask(Analysis, (
            "Summarize the page purpose and evidenced documents, deadlines, warnings and eligibility for the goal. "
            "Rewrite each form label and explain why and in what format it is requested. Use the requested locale. "
            "Preserve consent statement meaning exactly. Leave absent facts as empty arrays."
        ), {
            "goal": goal, "language": language, "title": snapshot.title, "headings": snapshot.headings,
            "visible_notices": snapshot.notices if include_brief else "",
            "accessibility": snapshot.ax if include_brief else [],
            "fields": [{"key": t.spec.key, "label": t.spec.original, "type": t.spec.kind, "required": t.spec.required,
                        "help": t.element["nearby_help_text"], "options": [o.label for o in t.spec.options[:15]]} for t in targets[:55]],
        })
        return Brief(**analysis.model_dump(exclude={"fields"}), source="llm"), {field.key: field for field in analysis.fields}, ""
    except ProviderUnavailable as error:
        return heuristic_brief(snapshot), {}, f"{error.code} · {error}"


def schema(snapshot: Snapshot, targets: list[Target]) -> TaskSchema:
    return TaskSchema(title=snapshot.title, url=snapshot.url, step=snapshot.step, fields=[target.spec for target in targets])


IRREVERSIBLE = re.compile(
    r"\b(submit|send|pay|purchase|buy|delete|remove permanently|confirm order|confirm booking|"
    r"place order|checkout|finali[sz]e|authorize|accept terms|certify|sign|file return|book now|"
    r"publish|transfer|withdraw|cancel subscription|confirm|proceed to payment|"
    r"enviar|pagar|supprimer|payer|soumettre|abschicken|bezahlen)\b",
    re.I,
)
PROGRESSION = re.compile(
    r"^(?:next\b|continue\b|proceed\b|review\b|save (?:and|&) continue\b|start (?:application|registration)\b|"
    r"begin(?: application)?\b|get started\b|apply now\b|register now\b|suivant\b|continuer\b|siguiente\b|continuar\b)",
    re.I,
)
EXCLUDED = re.compile(r"^(?:back\b|previous\b|cancel\b|close\b|help\b|learn more\b|log ?in\b|sign in\b|sign out\b)", re.I)


def risky(e: Element, snapshot: Snapshot) -> bool:
    label = " ".join([e.label, e["aria_label"]])
    final_step = re.search(r"(\d+)\s*(?:of|/)\s*(\d+)", snapshot.step)
    finishing = final_step and final_step[1] == final_step[2]
    return bool(e["type"] in {"submit", "image"} or IRREVERSIBLE.search(label) or
                (finishing and re.search(r"\b(apply|register|finish|complete)\b", label, re.I)))


class Plan(BaseModel):
    target: int | None
    classification: str = Field(pattern=r"^(advance|irreversible|none)$")


async def plan(llm: LLM, snapshot: Snapshot, goal: str) -> tuple[Element | None, bool, str]:
    controls = [
        e for e in snapshot.elements if not e["disabled"] and e.label
        and (e["tag"] in {"button", "a"} or e["role"] == "button" or e["type"] in {"submit", "button", "image"})
        and e["role"] in {"", "button", "link"} and e["type"] != "reset" and not EXCLUDED.search(e.label)
        and not e["href"].casefold().startswith(("javascript:", "mailto:", "tel:"))
    ][:80]
    if not controls:
        return None, False, ""
    notice = ""
    try:
        choice = await llm.ask(Plan, (
            "Select the numbered control that advances the stated workflow. Classify final submission, payments, legal consent, "
            "destructive actions and any uncertain state change as irreversible. Return null and none if no control clearly advances "
            "the goal. Do not choose account, sign-in, verification, cancel, unrelated links or help controls."
        ), {"goal": goal, "title": snapshot.title, "step": snapshot.step, "headings": snapshot.headings,
            "controls": [{"index": i, "label": e.label, "type": e["type"], "form_method": e["form_method"]} for i, e in enumerate(controls)]})
        if choice.classification != "none" and choice.target is not None and 0 <= choice.target < len(controls):
            e = controls[choice.target]
            return e, choice.classification == "irreversible" or risky(e, snapshot) or not PROGRESSION.search(e.label), ""
        if choice.target is None and choice.classification == "none":
            return None, False, ""
        notice = "INVALID_PLAN · The LLM selected an invalid control. Using local navigation analysis."
    except ProviderUnavailable as error:
        notice = f"{error.code} · {error}"
    forward = [e for e in controls if PROGRESSION.search(e.label)]
    committing = [e for e in controls if risky(e, snapshot)]
    if len(forward) == 1:
        return forward[0], risky(forward[0], snapshot), notice
    if not forward and len(committing) == 1:
        return committing[0], True, notice
    return None, False, notice


def receipt(snapshot: Snapshot) -> Receipt | None:
    confirmation = re.compile(
        r"\b(?:submission complete|successfully (?:submitted|registered|received)|"
        r"(?:application|registration|order|payment|request|booking|submission) "
        r"(?:(?:has been|was)\s+)?(?:received|confirmed|complete|successful|submitted)|"
        r"thank you for (?:applying|registering|your (?:application|order|submission)))\b", re.I,
    )
    lines = [*snapshot.headings, *snapshot.notices.splitlines(), *snapshot.context.splitlines()]
    summary = next((line for line in lines if confirmation.search(line) and not re.search(
        r"\b(?:before|when|after|once|until|will|incomplete)\b", line, re.I)), "")
    if not summary or any(field_kind(e) and e["required"] for e in snapshot.elements):
        return None
    text = "\n".join(lines)
    match = re.search(r"\b(?:reference|confirmation|receipt|transaction|application|booking)"
                      r"(?:\s+(?:number|id|code|no\.?))?\s*[:#]\s*([A-Z0-9][A-Z0-9/_-]{3,60})\b", text, re.I)
    return Receipt(reference=match[1] if match else None, summary=summary[:300], url=snapshot.url)
