import re
from dataclasses import dataclass


@dataclass
class GameTotalBreakdown:
    count: int
    rate: float
    total: float


@dataclass
class GameTotalSummary:
    total_entries: int
    total_amount: float
    breakdown: list[GameTotalBreakdown]
    text: str


def looks_like_game_message(value: str) -> bool:
    normalized = str(value or "").lower()
    number_count = len(re.findall(r"\d+", normalized))
    return (
        number_count >= 2
        or "into" in normalized
        or "intu" in normalized
        or "in to" in normalized
        or "rs" in normalized
        or "total" in normalized
        or "jc" in normalized
        or "jodi cut" in normalized
        or "joda cut" in normalized
        or "andar" in normalized
        or "bahar" in normalized
        or "ab" in normalized
        or "@" in normalized
        or "(" in normalized
    )


def _strip_user_written_total_hints(value: str) -> str:
    filtered_lines: list[str] = []
    for raw_line in str(value or "").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if re.fullmatch(r"\(?\s*\d+(?:\.\d+)?\s*(?:rs)?\s*[\])]?\s*", line, re.IGNORECASE):
            continue
        if re.fullmatch(
            r"(?:total|ttl|t)\s*(?:game|rupy|rs|rupees)?[\s.:=,\-]*\d+(?:\.\d+)?\s*(?:rs|rupees)?\s*",
            line,
            re.IGNORECASE,
        ):
            continue
        if re.fullmatch(r"total\b.*\b\d+(?:\.\d+)?\b.*", line, re.IGNORECASE):
            continue
        filtered_lines.append(line)
    return "\n".join(filtered_lines)


def _count_token_value(token: str, *, jodi_cut: bool = False, double_mode: bool = False) -> int:
    if not re.fullmatch(r"\d+", token):
        return 0
    if token in {"00", "100"}:
        return 2 if double_mode else 1
    if len(token) <= 2:
        return 2 if double_mode else 1
    if len(set(token)) == 1:
        return 2 if double_mode else 1
    unique_digit_count = len(set(token))
    base_count = unique_digit_count * unique_digit_count
    adjusted_count = max(unique_digit_count, base_count - unique_digit_count) if jodi_cut else base_count
    return adjusted_count * 2 if double_mode else adjusted_count


def _build_summary(segments: list[GameTotalBreakdown]) -> GameTotalSummary | None:
    if not segments:
        return None
    total_entries = sum(item.count for item in segments)
    total_amount = sum(item.total for item in segments)
    if not total_entries or not total_amount:
        return None
    lines = [f"{item.count} number x Rs {item.rate:g} = Rs {item.total:g}" for item in segments]
    lines.append(f"Total number: {total_entries}")
    lines.append(f"Total: Rs {total_amount:g}")
    return GameTotalSummary(
        total_entries=total_entries,
        total_amount=total_amount,
        breakdown=segments,
        text="Game total\n" + "\n".join(lines),
    )


def parse_fast_game_total_summary(value: str) -> GameTotalSummary | None:
    original = _strip_user_written_total_hints(value)
    normalized = original.replace("\r", "\n")

    if re.search(
        r"(last\s*time|signal|app|today|upi|paytm|phonepe|gpay|google\s*pay|payment|screenshot|qr|chart|call)",
        normalized,
        re.IGNORECASE,
    ):
        return None

    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    if not lines:
        return None

    ignored_words = {
        "gb",
        "gl",
        "g",
        "gali",
        "gaziybad",
        "ghaziabad",
        "delhi",
        "bajar",
        "bazaar",
        "ds",
        "dswr",
        "db",
        "dl",
        "fd",
        "fb",
        "offline",
        "working",
        "ok",
        "ki",
        "mein",
        "main",
        "me",
        "mi",
        "shri",
        "ganesh",
        "tolla",
        "total",
        "game",
    }

    def extract_rate(line: str) -> float | None:
        lower = line.lower()
        patterns = [
            r"^\s*\d{1,3}[.,/-](\d+(?:\.\d+)?)\s*$",
            r"\b(?:into|intu|in to)\s*(\d+(?:\.\d+)?)",
            r"\((\d+(?:\.\d+)?)\)",
            r"@+\s*(\d+(?:\.\d+)?)",
            r"(?:^|[\s])(\d+(?:\.\d+)?)\s*rs\b",
            r"-(\d+(?:\.\d+)?)\s*rs-",
        ]
        for pattern in patterns:
            match = re.search(pattern, lower, re.IGNORECASE)
            if match:
                return float(match.group(1))
        return None

    def is_standalone_total_hint_line(line: str) -> bool:
        lower = line.lower().strip()
        return bool(
            re.fullmatch(r"\(?\s*\d+(?:\.\d+)?\s*(?:rs)?\s*[\])]?\s*", lower)
            or re.fullmatch(r"(?:total|ttl|t)\s*[:.= -]?\s*\d+(?:\.\d+)?\s*(?:rs)?\s*", lower, re.IGNORECASE)
        )

    def extract_number_tokens(line: str) -> list[str]:
        compact_match = re.fullmatch(r"\s*(\d{1,3})[.,/-](\d+(?:\.\d+)?)\s*", line)
        if compact_match:
            return [compact_match.group(1)]
        scrubbed = re.sub(r"\b(?:into|intu|in to)\s*\d+(?:\.\d+)?", " ", line, flags=re.IGNORECASE)
        scrubbed = re.sub(r"\(\d+(?:\.\d+)?\)", " ", scrubbed)
        scrubbed = re.sub(r"@+\s*\d+(?:\.\d+)?", " ", scrubbed)
        scrubbed = re.sub(r"\b\d+(?:\.\d+)?\s*rs\b", " ", scrubbed, flags=re.IGNORECASE)
        scrubbed = re.sub(r"-\d+(?:\.\d+)?\s*rs-", " ", scrubbed, flags=re.IGNORECASE)
        return [token for token in re.findall(r"\d{1,3}", scrubbed) if token.lower() not in ignored_words]

    segments: list[GameTotalBreakdown] = []
    pending_count = 0

    for line in lines:
        harf_match = re.search(
            r"((?:\d+\s*[-.,/]*\s*)+)\s*harf\s*-\s*b\s*-\s*ka\s*-\s*\(?\s*(\d+(?:\.\d+)?)\s*-\s*rs\s*-\s*\)?",
            line,
            re.IGNORECASE,
        )
        if harf_match:
            digits = re.findall(r"\d+", harf_match.group(1))
            rate = float(harf_match.group(2))
            if digits and rate > 0:
                segments.append(GameTotalBreakdown(count=len(digits), rate=rate, total=len(digits) * rate))
                continue

        if is_standalone_total_hint_line(line):
            continue

        rate = extract_rate(line)
        tokens = extract_number_tokens(line)
        line_count = sum(_count_token_value(token) for token in tokens)

        if rate and line_count > 0:
            combined_count = pending_count + line_count
            segments.append(GameTotalBreakdown(count=combined_count, rate=rate, total=combined_count * rate))
            pending_count = 0
            continue

        if rate and pending_count > 0:
            segments.append(GameTotalBreakdown(count=pending_count, rate=rate, total=pending_count * rate))
            pending_count = 0
            continue

        pending_count += line_count

    return _build_summary(segments)


def parse_game_total_summary(value: str) -> GameTotalSummary | None:
    normalized_value = _strip_user_written_total_hints(value)
    normalized_value = re.sub(r"([A-Za-z]+)(\d)", r"\1 \2", normalized_value)
    normalized_value = re.sub(r"(\d)([A-Za-z]+)", r"\1 \2", normalized_value)
    normalized_value = normalized_value.replace("\r", "\n")
    normalized_value = normalized_value.replace("₹", " Rs ")
    normalized_value = re.sub(
        r"((?:\d{1,3}_){2,})(\d+(?:\.\d+)?)\s*(?:in\s*to|into|intu)\b",
        lambda match: f" {' '.join(token for token in match.group(1).split('_') if token)} RATE:{match.group(2)} ",
        normalized_value,
        flags=re.IGNORECASE,
    )
    replacements = [
        (r"\(\s*(\d+(?:\.\d+)?)\s*-\s*Rs\s*-\s*\)", r" RATE:\1 "),
        (r"\(\s*(\d+(?:\.\d+)?)\s*rs\s*-\s*\)", r" RATE:\1 "),
        (r"\(\s*(\d+(?:\.\d+)?)\s*Rs\s*\)", r" RATE:\1 "),
        (r"(\))(?=\d)", r"\1\n"),
        (r"(\d)(\()", r"\1 \2"),
        (r"([0-9, ]+),{2,}[ \t]*(\d+(?:\.\d+)?)\b", r"\1 RATE:\2 \n"),
        (r"([0-9,\.\s]+)\+{2,}\s*([0-9]+)\b", r"\1 RATE:\2 "),
        (r"([0-9,\.\s]+)\*{2,}\s*([0-9]+)\b", r"\1 RATE:\2 "),
        (r"([0-9\s,./]+)@+\s*([0-9]+)\b", r"\1 RATE:\2 "),
        (r"([0-9,\.\s]+)[xX]\s*([0-9]+)\b", r"\1 RATE:\2 "),
        (r"([0-9]+)\s*(?:in\s*to|into|intu)\s*([0-9]+)\s*rs\b", r" \1 RATE:\2 "),
        (r"([0-9])\s*(?:in\s*to|into|intu)\b", r"\1 INTO"),
        (r"\b(?:in\s*to|into|intu)\s*₹?\s*(\d+(?:\.\d+)?)", r" RATE:\1 "),
        (r"\(\s*₹?\s*(\d+(?:\.\d+)?)\s*\)", r" RATE:\1 "),
        (r"([0-9]+)\s*(?:in\s*to|into|intu)\b", r" RATE:\1 "),
        (r"([0-9]+)\s*rs\b", r" RATE:\1 "),
        (r"([0-9]+)\s*[@=_]{1,3}\s*([0-9]+)\b", r"\1 RATE:\2 "),
        (r"([0-9]+)\s*(?:={1,3}|_{1,3}|@)\s*([0-9]+)\b", r"\1 RATE:\2 "),
        (r"\btotal(?:\s*game)?[\s.:=-]*(\d+(?:\.\d+)?)", r" TOTAL:\1 "),
        (r"\bttl[\s.:=-]*(\d+(?:\.\d+)?)", r" TOTAL:\1 "),
        (r"\bt[\s.:=-]*(\d+(?:\.\d+)?)", r" TOTAL:\1 "),
        (r"\b(\d+(?:\.\d+)?)t\b", r" TOTAL:\1 "),
        (r"[|;]+", "\n"),
        (r"(\d)\s*-\s*(?=\d)", r"\1 "),
        (r",", " "),
        (r"[./]+", " "),
        (r"[ \t]+", " "),
    ]
    for pattern, replacement in replacements:
        normalized_value = re.sub(pattern, replacement, normalized_value, flags=re.IGNORECASE)

    if re.search(
        r"(last\s*time|signal|app|today|upi|paytm|phonepe|gpay|google\s*pay|payment|screenshot|qr|chart|call)",
        normalized_value,
        re.IGNORECASE,
    ):
        return None

    raw_lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    raw_blocks = [
        [line.strip() for line in block.splitlines() if line.strip()]
        for block in re.split(r"\r?\n\s*\r?\n+", str(value or ""))
        if block.strip()
    ]
    ignored_words = re.compile(
        r"^(gb|gl|g|gali|gaziybad|ghaziabad|delhi|bajar|bazaar|ds|dswr|offline|working|ok|jc|b|bb|bhar|ab|with|plt|m|w|db|ki|mein|main|me|mi|fd|fb|dl|harup|andar|bahar|gzb|gli|desawar|disawar|shri|ganesh)$",
        re.IGNORECASE,
    )

    def build_segment(token_count: int, rate: float) -> GameTotalBreakdown | None:
        if not token_count or not rate or rate <= 0:
            return None
        return GameTotalBreakdown(count=token_count, rate=rate, total=token_count * rate)

    def scoped_count(tokens: list[str], *, jodi_cut: bool = False, double_mode: bool = False) -> int:
        return sum(
            _count_token_value(token, jodi_cut=jodi_cut, double_mode=double_mode)
            for token in tokens
        )

    def direct_line_segments(line: str, *, jodi_cut: bool = False, double_mode: bool = False) -> list[GameTotalBreakdown]:
        direct_tokens = [
            token
            for token in re.split(r"\s+", line)
            if token.strip() and not ignored_words.fullmatch(token.strip())
        ]
        if not direct_tokens:
            return []
        segments: list[GameTotalBreakdown] = []
        for token in direct_tokens:
            normalized_token = re.sub(r"[(),]+", "", token)
            match = re.fullmatch(r"(\d{1,3})\s*[-=@_]\s*(\d+(?:\.\d+)?)", normalized_token)
            if not match:
                match = re.fullmatch(r"(\d{1,3})\s*RATE:(\d+(?:\.\d+)?)", normalized_token, re.IGNORECASE)
            if not match:
                return []
            count = _count_token_value(match.group(1), jodi_cut=jodi_cut, double_mode=double_mode)
            rate = float(match.group(2))
            if not count or rate <= 0:
                return []
            segments.append(GameTotalBreakdown(count=count, rate=rate, total=count * rate))
        return segments

    def hint_scoped_line_segments(line: str, *, jodi_cut: bool = False, double_mode: bool = False) -> list[GameTotalBreakdown]:
        compact_line = re.sub(r"[ ]+", " ", re.sub(r"\b(?:rs|ki|main|mein|me|gali|gb|gl|ds|fd|db|dl)\b", " ", re.sub(r"[|;]", " ", line), flags=re.IGNORECASE)).strip()
        if not compact_line:
            return []

        underscore_match = re.fullmatch(r"((?:\d{1,3}_){2,})(\d+(?:\.\d+)?)\s*(?:in\s*to|into|intu)\s*", compact_line, re.IGNORECASE)
        if underscore_match:
            tokens = [token.strip() for token in underscore_match.group(1).split("_") if token.strip()]
            segment = build_segment(scoped_count(tokens, jodi_cut=jodi_cut, double_mode=double_mode), float(underscore_match.group(2)))
            if segment:
                return [segment]

        direct_segments = direct_line_segments(compact_line, jodi_cut=jodi_cut, double_mode=double_mode)
        if direct_segments:
            return direct_segments

        pair_tokens = re.findall(r"\d{1,3}\s*[-=@_]\s*\d+(?:\.\d+)?", compact_line)
        if pair_tokens:
            rebuilt = [segment for token in pair_tokens for segment in direct_line_segments(token, jodi_cut=jodi_cut, double_mode=double_mode)]
            if len(rebuilt) == len(pair_tokens):
                return rebuilt

        patterns = [
            r"((?:\d{1,3}[\s,./_-]*)+)\(\s*(\d+(?:\.\d+)?)\s*\)\s*$",
            r"((?:\d{1,3}[\s,./_-]*)+)(\d+(?:\.\d+)?)\s*(?:in\s*to|into|intu)\s*$",
            r"((?:\d{1,3}[\s,./_-]*)+)(?:in\s*to|into|intu)\s*(\d+(?:\.\d+)?)\s*$",
            r"((?:\d{1,3}[\s,./_-]*)+)[@=_-]\s*(\d+(?:\.\d+)?)\s*$",
            r"((?:\d{1,3}[\s,./-]*)+)[.,]{2,}\s*(\d+(?:\.\d+)?)\s*$",
        ]
        for pattern in patterns:
            match = re.fullmatch(pattern, compact_line, re.IGNORECASE)
            if not match:
                continue
            tokens = re.findall(r"\d{1,3}", match.group(1))
            segment = build_segment(scoped_count(tokens, jodi_cut=jodi_cut, double_mode=double_mode), float(match.group(2)))
            if segment:
                return [segment]
        return []

    def plain_line_token_count(line: str, *, jodi_cut: bool = False, double_mode: bool = False) -> int:
        compact_line = re.sub(
            r"[ ]+",
            " ",
            re.sub(
                r"\b(?:rs|ki|main|mein|me|gali|gb|gl|ds|fd|db|dl|into|intu|in\s*to|total|game|tolla)\b",
                " ",
                re.sub(r"[|;]+", " ", line),
                flags=re.IGNORECASE,
            ),
        ).strip()
        if not compact_line:
            return 0
        return scoped_count(re.findall(r"\d{1,3}", compact_line), jodi_cut=jodi_cut, double_mode=double_mode)

    def parse_block_segments(block_lines: list[str], *, jodi_cut: bool = False, double_mode: bool = False) -> list[GameTotalBreakdown]:
        block_segments: list[GameTotalBreakdown] = []
        pending_count = 0
        for line in block_lines:
            line_segments = hint_scoped_line_segments(line, jodi_cut=jodi_cut, double_mode=double_mode)
            if line_segments:
                if len(line_segments) == 1 and pending_count > 0:
                    segment = line_segments[0]
                    block_segments.append(
                        GameTotalBreakdown(
                            count=segment.count + pending_count,
                            rate=segment.rate,
                            total=(segment.count + pending_count) * segment.rate,
                        )
                    )
                    pending_count = 0
                    continue
                pending_count = 0
                block_segments.extend(line_segments)
                continue
            pending_count += plain_line_token_count(line, jodi_cut=jodi_cut, double_mode=double_mode)
        return block_segments

    block_segments = []
    for block in raw_blocks:
        block_text = " ".join(block)
        block_segments.extend(
            parse_block_segments(
                block,
                jodi_cut=bool(re.search(r"(jc|jodi\s*cut|joda\s*cut|jodi\s*kati|cut\s*joda|cut\s*jodi)", block_text, re.IGNORECASE)),
                double_mode=bool(re.search(r"\bab\b|andar\s*bahar|andar\s+bhar|andar\b.*bahar|bahar\b.*andar", block_text, re.IGNORECASE)),
            )
        )

    if block_segments:
        grouped: dict[float, GameTotalBreakdown] = {}
        for item in block_segments:
            current = grouped.get(item.rate)
            if current is None:
                grouped[item.rate] = GameTotalBreakdown(count=item.count, rate=item.rate, total=item.total)
            else:
                current.count += item.count
                current.total += item.total
        summary = _build_summary(sorted(grouped.values(), key=lambda item: item.rate, reverse=True))
        if summary:
            return summary

    raw_direct_segments = []
    for line in raw_lines:
        raw_direct_segments.extend(
            hint_scoped_line_segments(
                line,
                jodi_cut=bool(re.search(r"(jc|jodi\s*cut|joda\s*cut|jodi\s*kati|cut\s*joda|cut\s*jodi)", line, re.IGNORECASE)),
                double_mode=bool(re.search(r"\bab\b|andar\s*bahar|andar\s+bhar|andar\b.*bahar|bahar\b.*andar", line, re.IGNORECASE)),
            )
        )
    if raw_direct_segments:
        summary = _build_summary(raw_direct_segments)
        if summary:
            return summary

    lines = [line.strip() for line in normalized_value.splitlines() if line.strip()]
    segments: list[GameTotalBreakdown] = []
    carry_rate: float | None = None
    pending_buffered_count = 0

    for line in lines:
        has_jodi_cut = bool(re.search(r"(jc|jodi\s*cut|joda\s*cut|jodi\s*kati|cut\s*joda|cut\s*jodi)", line, re.IGNORECASE))
        has_double_mode = bool(re.search(r"\bab\b|andar\s*bahar|andar\s+bhar|andar\b.*bahar|bahar\b.*andar", line, re.IGNORECASE))
        line_numbers = re.findall(r"\d+", line)
        should_carry_rate = bool(re.fullmatch(r"(\d+\s*)+RATE:\d+(?:\.\d+)?", line, re.IGNORECASE)) and len(line_numbers) <= 2
        direct_segments = direct_line_segments(line, jodi_cut=has_jodi_cut, double_mode=has_double_mode)
        if direct_segments:
            segments.extend(direct_segments)
            carry_rate = None
            continue

        pending_count = 0
        for token in [token.strip() for token in re.split(r"\s+", line) if token.strip()]:
            if ignored_words.fullmatch(token):
                continue
            rate_match = re.fullmatch(r"RATE:(\d+(?:\.\d+)?)", token, re.IGNORECASE)
            if rate_match:
                rate = float(rate_match.group(1))
                combined_count = pending_buffered_count + pending_count
                if combined_count <= 0:
                    carry_rate = rate
                else:
                    segment = GameTotalBreakdown(count=combined_count, rate=rate, total=combined_count * rate)
                    segments.append(segment)
                    pending_count = 0
                    pending_buffered_count = 0
                    carry_rate = rate if should_carry_rate else None
                continue
            if re.fullmatch(r"TOTAL:(\d+(?:\.\d+)?)", token, re.IGNORECASE):
                continue
            if re.fullmatch(r"\d+", token):
                pending_count += _count_token_value(token, jodi_cut=has_jodi_cut, double_mode=has_double_mode)

        if pending_count > 0 and carry_rate:
            segments.append(GameTotalBreakdown(count=pending_count, rate=carry_rate, total=pending_count * carry_rate))
        elif pending_count > 0:
            pending_buffered_count += pending_count

    return _build_summary(segments)


def calculate_game_total_summary(value: str) -> GameTotalSummary | None:
    if not looks_like_game_message(value):
        return None
    return parse_fast_game_total_summary(value) or parse_game_total_summary(value)


def build_game_total_reply(value: str) -> tuple[bool, str, GameTotalSummary | None]:
    summary = calculate_game_total_summary(value)
    if not summary:
        return False, "Ye game samajh nahi aayi, isliye total nahi nikla.", None
    return True, summary.text, summary
