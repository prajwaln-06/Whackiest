import re
from pathlib import Path

from pydantic import BaseModel, Field
from pypdf import PdfReader

from app.agent.scout import Target, normalize, phrase
from app.llm.client import LLM, ProviderUnavailable
from app.models.schemas import Value, Vault


IDENTITIES = {
    "name": {"name", "full name", "legal name", "applicant name"},
    "given-name": {"first name", "given name", "forename"},
    "family-name": {"last name", "family name", "surname"},
    "email": {"email", "email address", "e mail"},
    "tel": {"tel", "phone", "phone number", "telephone", "mobile", "mobile number"},
    "bday": {"bday", "birthday", "date of birth", "birth date", "dob"},
    "country": {"country", "country name", "country of residence", "domicile"},
    "postal-code": {"postal code", "postcode", "zip", "zip code"},
    "street-address": {"street address", "address", "address line 1", "address line one"},
    "address-level2": {"city", "town", "address level2"},
    "address-level1": {"state", "province", "region", "address level1"},
    "organization": {"organization", "organization name", "company", "company name", "institution name"},
}
ALIAS = {name: standard for standard, aliases in IDENTITIES.items() for name in aliases}
DECISION = re.compile(
    r"\b(?:accept|agree|consent|permission|confirm|certif\w*|declare|legal\s+terms|authorization|"
    r"pay|purchase|payment|filing frequency|tax cadence|applicant type|eligibility)\b", re.I,
)
SENSITIVE = re.compile(
    r"\b(?:password|pin|otp|one time code|security code|passcode|card number|cvv|cvc|secret|bank account)\b", re.I,
)


def identity(value: str) -> str:
    value = normalize(phrase(value))
    return ALIAS.get(value, value)


def identities(target: Target) -> set[str]:
    e, spec = target.element, target.spec
    names = {identity(item) for item in (spec.original, e["name"], e["id"], spec.label) if item}
    autocomplete = e["autocomplete"].split()
    if autocomplete and autocomplete[-1] in IDENTITIES:
        names.add(autocomplete[-1])
    return names


def option_value(target: Target, answer: Value) -> Value:
    if isinstance(answer, list):
        return [str(option_value(target, part)) for part in answer]
    if not isinstance(answer, str):
        return answer
    exact = [option for option in target.spec.options if option.value == answer]
    if exact or not target.spec.options:
        return answer
    by_label = [option for option in target.spec.options if normalize(option.label) == normalize(answer)]
    return by_label[0].value if len(by_label) == 1 else answer


def is_set(value: Value) -> bool:
    return value is not None and value is not False and value != "" and value != []


def valid_answer(target: Target, answer: Value) -> bool:
    spec = target.spec
    if spec.kind == "checkbox":
        return isinstance(answer, bool) and (answer or not spec.required)
    if not is_set(answer):
        return not spec.required
    if spec.multiple and isinstance(answer, list):
        return all(isinstance(item, str) and (
            not spec.options or item in {option.value for option in spec.options}
        ) for item in answer)
    if isinstance(answer, str) and answer.strip():
        return not spec.options or answer in {option.value for option in spec.options}
    return False


def suggest(target: Target, vault: Vault, memory: dict[str, dict[str, Value]], current: dict[str, Value]):
    spec = target.spec
    label = normalize(spec.original)
    if spec.kind in {"checkbox", "file", "radio", "password"} or DECISION.search(label) or SENSITIVE.search(label):
        return
    names = identities(target)
    if len(names) == 0:
        return
    previous = {str(value): value for name in names for key, value in memory.get(name, {}).items()
                if key != spec.key and is_set(value)}
    if len(previous) == 1:
        answer = option_value(target, next(iter(previous.values())))
        if valid_answer(target, answer):
            spec.suggestion, spec.confidence, spec.source = answer, 0.99, "previous"
            return
    options = []
    for key, raw in vault.facts.items():
        if SENSITIVE.search(normalize(key)) or identity(key) not in names:
            continue
        value = option_value(target, raw)
        if valid_answer(target, value):
            options.append(value)
    if len(set(options)) == 1 and spec.key not in current:
        spec.suggestion, spec.confidence, spec.source = options[0], 0.97, "vault"


class DocumentFact(BaseModel):
    key: str = Field(max_length=100)
    value: str = Field(max_length=5000)


class DocumentFacts(BaseModel):
    facts: list[DocumentFact] = Field(max_length=60)


def document_text(path: Path) -> str:
    if path.suffix.lower() in {".txt", ".md", ".csv"}:
        with path.open("rb") as file:
            return file.read(120000).decode("utf-8-sig", errors="replace")[:16000]
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("Use an unlocked PDF.")
        blocks = []
        for page in reader.pages[:12]:
            blocks.append((page.extract_text() or "")[:16000])
            if sum(map(len, blocks)) >= 16000:
                break
        return "\n".join(blocks)[:16000]
    raise ValueError("Choose a PDF or TXT document.")


async def extract_facts(llm: LLM, text: str) -> tuple[Vault, str]:
    if not text.strip():
        return Vault(), "No selectable text was found in the document."
    try:
        result = await llm.ask(DocumentFacts, (
            "Extract explicitly stated profile facts from the document. Use canonical keys such as full_name, email, "
            "phone, date_of_birth in YYYY-MM-DD, country, city, organization, and website. "
            "Exclude all passwords, payment card numbers, PINs, one-time codes and secrets. Do not infer a value."
        ), {"document_text": text})
        return Vault(facts={pair.key: pair.value for pair in result.facts if not SENSITIVE.search(normalize(pair.key))}), ""
    except ProviderUnavailable as error:
        facts = {}
        for line in text.splitlines()[:500]:
            if match := re.match(r"^\s*([\w /-]{2,70})\s*[:=]\s*(.{1,5000})$", line):
                key, value = match.groups()
                if not SENSITIVE.search(normalize(key)):
                    facts[key.strip()] = value.strip()
        if "email" not in {identity(key) for key in facts}:
            emails = set(re.findall(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", text))
            if len(emails) == 1:
                facts["email"] = emails.pop()
        return Vault(facts=dict(list(facts.items())[:60])), f"{error.code} · {error}"
