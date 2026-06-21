import argparse
import html
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://vos.olimpiada.ru/team/year/{year}/results"

START_MARKER_A = "\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u044b \u043a\u043e\u043c\u0430\u043d\u0434\u044b \u041c\u043e\u0441\u043a\u0432\u044b"
START_MARKER_B = "\u0437\u0430\u043a\u043b\u044e\u0447\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u043c \u044d\u0442\u0430\u043f\u0435"

WINNER_STATUS = "\u043f\u043e\u0431\u0435\u0434\u0438\u0442\u0435\u043b\u044c"
PRIZER_STATUS = "\u043f\u0440\u0438\u0437\u0435\u0440"

GRADE_RE = re.compile(r"^(\d{1,2})\s*\u043a\u043b\u0430\u0441\u0441:\s*$", re.IGNORECASE)
PARTICIPANT_RE = re.compile(r"^(?:\d+\.\s+)?(.+?)\s*,\s+(.+)$")
SUBJECT_DOT_RE = re.compile(r"^\d{1,2}\s*(?:-\s*\d{1,2})?\s+[^.,]+\.?\s*\.\s*(.+)$")
SUBJECT_COMMA_RE = re.compile(r"^\d{1,2}\s+[^,]+,\s*(.+)$")
WINNERS_RE = re.compile(r"^\s*\u041f\u043e\u0431\u0435\u0434\u0438\u0442\u0435\u043b\u0438\s*$", re.IGNORECASE)
PRIZERS_RE = re.compile(r"^\s*\u041f\u0440\u0438\u0437[\u0435\u0451]\u0440\u044b\s*$", re.IGNORECASE)


def _normalize_spaces(text: str) -> str:
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _split_full_name(full_name: str) -> list[str]:
    parts = full_name.split()
    surname = parts[0] if len(parts) > 0 else ""
    name = parts[1] if len(parts) > 1 else ""
    patronymic = " ".join(parts[2:]) if len(parts) > 2 else ""
    return [surname, name, patronymic]


def _extract_subject(line: str) -> str | None:
    line = _normalize_spaces(line)

    match = SUBJECT_DOT_RE.match(line)
    if match:
        raw = match.group(1)
    else:
        match = SUBJECT_COMMA_RE.match(line)
        if not match:
            return None
        raw = match.group(1)

    # Trim trailing location in parentheses: "... (Moscow region)".
    subject = re.sub(r"\s*\([^()]*\)\s*$", "", raw).strip(" .")
    return subject or None


def _html_to_lines(page_html: str) -> list[str]:
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", page_html)
    cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|section|article)>", "\n", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)

    lines: list[str] = []
    for raw_line in cleaned.splitlines():
        normalized = _normalize_spaces(raw_line)
        if normalized:
            lines.append(normalized)
    return lines


def parse_results(year: int) -> list[list[str]]:
    """
    Parse https://vos.olimpiada.ru/team/year/<year>/results and return rows:
    [surname, name, patronymic, school, grade, subject, status]

    where status is one of: "победитель", "призер".
    """
    url = BASE_URL.format(year=year)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        )
    }

    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            page_html = response.read().decode("utf-8", errors="replace")
    except HTTPError as err:
        raise RuntimeError(f"HTTP error {err.code} for {url}") from err
    except URLError as err:
        raise RuntimeError(f"Network error for {url}: {err.reason}") from err

    lines = _html_to_lines(page_html)

    start_idx: int | None = None
    for idx, line in enumerate(lines):
        if START_MARKER_A in line and START_MARKER_B in line:
            start_idx = idx
            break

    if start_idx is None:
        raise RuntimeError("Could not find results block on the page. Page structure may have changed.")

    rows: list[list[str]] = []
    current_subject: str | None = None
    current_grade: str | None = None
    current_status: str | None = None

    for line in lines[start_idx:]:
        subject = _extract_subject(line)
        if subject:
            current_subject = subject
            current_grade = None
            current_status = None
            continue

        if WINNERS_RE.match(line):
            current_status = WINNER_STATUS
            current_grade = None
            continue

        if PRIZERS_RE.match(line):
            current_status = PRIZER_STATUS
            current_grade = None
            continue

        grade_match = GRADE_RE.match(line)
        if grade_match:
            current_grade = grade_match.group(1)
            continue

        participant_match = PARTICIPANT_RE.match(line)
        if participant_match and current_subject and current_grade and current_status:
            full_name = _normalize_spaces(participant_match.group(1))
            school = _normalize_spaces(participant_match.group(2))
            if len(full_name.split()) < 2:
                continue
            surname, name, patronymic = _split_full_name(full_name)
            rows.append(
                [
                    surname,
                    name,
                    patronymic,
                    school,
                    current_grade,
                    current_subject,
                    current_status,
                ]
            )

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse winners and prize-winners from vos.olimpiada.ru/team/year/<year>/results"
    )
    parser.add_argument("year", type=int, help="Year in URL, for example 2026")
    args = parser.parse_args()

    result = parse_results(args.year)
    print(result)


if __name__ == "__main__":
    main()
