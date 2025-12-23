import re
from typing import Dict, Any, List


PRIORITY_MAP = {
    "visok": "High",
    "visoka": "High",
    "srednji": "Medium",
    "srednja": "Medium",
    "nizak": "Low",
    "niska": "Low",
}

STATUS_MAP = {
    "aktivan": "Active",
    "aktivno": "Active",
    "active": "Active",
    "not started": "Not Started",
    "nije zapoceto": "Not Started",
    "nije započeto": "Not Started",
}


def _normalize_quotes(text: str) -> str:
    return text.replace("“", '"').replace("”", '"').strip()


def _map_priority(value: str) -> str:
    v = value.strip().lower()
    return PRIORITY_MAP.get(v, value.strip())


def _map_status(value: str) -> str:
    v = value.strip().lower()
    return STATUS_MAP.get(v, value.strip())


def parse_ceo_goal_plan(text: str) -> Dict[str, Any]:
    """
    Parsira CEO NL komandu tipa:

    Kreiraj centralni cilj “Implementirati FLP Manager operativni sistem”
    sa due date 01.05.2025, prioritet Visok, status Aktivan.
    Kreiraj tri podcilja:
    ...

    Vraća strukturirani plan koji poslije pretvaramo u AICommand.
    """
    text_norm = _normalize_quotes(text)

    # ------------------------------------------------------------
    # CENTRALNI CILJ
    # ------------------------------------------------------------
    m = re.search(
        r'Kreiraj centralni cilj\s+"(?P<name>.+?)"\s+sa due date\s+'
        r"(?P<date>\d{2}\.\d{2}\.\d{4}),\s*prioritet\s+"
        r"(?P<priority>\w+),\s*status\s+(?P<status>[^.\n]+)",
        text_norm,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not m:
        raise ValueError("Ne mogu parsirati centralni cilj iz CEO komande.")

    central_name = m.group("name").strip()
    date_raw = m.group("date")
    prio_raw = m.group("priority").strip()
    status_raw = m.group("status").strip()

    # dd.mm.yyyy -> yyyy-mm-dd
    day, month, year = map(int, date_raw.split("."))
    iso_date = f"{year:04d}-{month:02d}-{day:02d}"

    central_goal = {
        "name": central_name,
        "due_date": iso_date,
        "priority": _map_priority(prio_raw),
        "status": _map_status(status_raw),
    }

    # ------------------------------------------------------------
    # PODCILJEVI
    # ------------------------------------------------------------
    subgoals: List[Dict[str, Any]] = []
    sub_section_match = re.search(
        r"Kreiraj tri podcilja:(?P<body>.+?)Kreiraj 7-dnevni plan taskova",
        text_norm,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if sub_section_match:
        body = sub_section_match.group("body")
        for line in body.splitlines():
            line = line.strip().strip(",")
            if not line:
                continue

            mm = re.search(
                r"^(?P<name>.+?)\s*\(prioritet\s+(?P<priority>[^)]+)\)",
                line,
                flags=re.IGNORECASE,
            )
            if not mm:
                continue

            name = mm.group("name").strip(" •-")
            pr = mm.group("priority").strip()

            subgoals.append(
                {
                    "name": name,
                    "priority": _map_priority(pr),
                }
            )

    # ------------------------------------------------------------
    # 7-DNEVNI TASK PLAN
    # ------------------------------------------------------------
    tasks: List[Dict[str, Any]] = []
    tasks_section = re.search(
        r"Kreiraj 7-dnevni plan taskova.+?:\s*(?P<body>.+)",
        text_norm,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if tasks_section:
        body = tasks_section.group("body")
        for line in body.splitlines():
            line = line.strip().strip(",")
            if not line:
                continue

            mm = re.search(
                r"^Dan\s+(?P<day>\d+):\s*(?P<name>.+?)\s*\((?P<priority>[^)]+)\)",
                line,
                flags=re.IGNORECASE,
            )
            if not mm:
                continue

            day = int(mm.group("day"))
            name = mm.group("name").strip()
            pr = mm.group("priority").strip()

            tasks.append(
                {
                    "day": day,
                    "name": name,
                    "priority": _map_priority(pr),
                }
            )

    return {
        "central_goal": central_goal,
        "subgoals": subgoals,
        "tasks": tasks,
    }
