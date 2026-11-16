"""Realistic content for the scripted model: a small SQL path with real skill names, one real lesson text
and real review questions. Used for design screenshots and for live checks of single stages, where the
repeated filler of `fakes.py` would hide how a screen reads. No network, no cost.
"""

import re
from typing import Any

from yuo.core.llm import Request

BRANCHES: list[tuple[str, str, list[tuple[str, str, str, str]]]] = [
    (
        "basics",
        "Query basics",
        [
            (
                "select",
                "Selecting columns",
                "Read the columns you need from one table.",
                "Write a SELECT that returns chosen columns",
            ),
            (
                "filter",
                "Filtering rows",
                "Keep only the rows that match a condition.",
                "Filter rows with WHERE, AND, OR and IN",
            ),
            (
                "sort",
                "Sorting and limiting",
                "Order results and take the top rows.",
                "Sort results and limit them to the top rows",
            ),
        ],
    ),
    (
        "joins",
        "Combining tables",
        [
            ("inner", "Inner joins", "Match rows of two tables on a key.", "Join two tables on a shared key"),
            (
                "outer",
                "Outer joins",
                "Keep rows that have no match.",
                "Choose between inner, left and full joins",
            ),
            (
                "self",
                "Self joins",
                "Compare rows of one table with each other.",
                "Join a table to itself to compare its rows",
            ),
        ],
    ),
    (
        "summaries",
        "Summaries",
        [
            (
                "group",
                "Grouping and aggregates",
                "Count, sum and average per group.",
                "Summarise rows with GROUP BY and aggregates",
            ),
            (
                "having",
                "Filtering groups",
                "Keep only the groups that pass a test.",
                "Tell WHERE from HAVING and use each correctly",
            ),
            (
                "window",
                "Window functions",
                "Rank and compare rows without collapsing them.",
                "Rank rows and compute running totals with window functions",
            ),
        ],
    ),
]
# prerequisites across branches: joins need filtering, grouping needs inner joins, windows need sorting
EXTRA_REQUIRES = {
    "sql.joins.inner": ["sql.basics.filter"],
    "sql.summaries.group": ["sql.joins.inner"],
    "sql.summaries.window": ["sql.basics.sort"],
}


def tree() -> dict[str, Any]:
    branches = []
    for bcode, btitle, skills in BRANCHES:
        out = []
        prev: str | None = None
        for scode, title, summary, objective in skills:
            code = f"sql.{bcode}.{scode}"
            requires = ([prev] if prev else []) + EXTRA_REQUIRES.get(code, [])
            out.append(
                {
                    "code": code,
                    "title": title,
                    "summary": summary,
                    "requires": requires,
                    "objectives": [{"code": f"{code}.o1", "statement": objective, "bloom_level": "apply"}],
                    "lessons": [{"code": f"{code}.l1", "title": title}],
                }
            )
            prev = code
        branches.append({"code": f"sql.{bcode}", "title": btitle, "skills": out})
    return {"branches": branches}


LESSON_PARAGRAPHS = [
    "Most questions about data span more than one table. A shop keeps its customers in one table and their "
    "orders in another, because a customer can place many orders and repeating the customer's name and city "
    "on every order would waste space and invite mistakes. The two tables are linked by a **key**: each "
    "order row carries the `customer_id` of the customer who placed it. A **join** follows that link. It "
    "builds result rows by pairing a row from one table with the rows of the other table that share the "
    "same key value.",
    "An **inner join** keeps a pair only when both sides have a match. Join customers to orders on "
    "`customer_id` and you get one result row per order, with the customer's columns next to the order's "
    "columns. A customer with three orders appears three times. A customer with no orders does not appear "
    "at all, and neither does an order whose `customer_id` points at nobody. That last property is what "
    "people forget: an inner join silently drops rows that have no partner, so a total computed after the "
    "join can be smaller than the total of the table you started from.",
    "A **left join** keeps every row of the table named first, the left one, whether or not it has a match. "
    "Where there is no match, the columns that would have come from the right table are filled with "
    "`NULL`. Start from customers, left join orders, and customers without orders stay in the result with "
    "empty order columns. This is the join for questions that contain the words *every*, *all* or *even "
    "those without*: every customer and their orders, all products and whatever reviews they have. A right "
    "join is the mirror image, and a **full join** keeps unmatched rows from both sides.",
    "Because unmatched rows carry `NULL`, a left join is also the standard way to find what is missing. "
    "Left join customers to orders and keep only the rows where the order's id `IS NULL`: those are the "
    "customers who never ordered. Be careful where you put other conditions, though. A filter on the right "
    "table written in `WHERE` runs after the join and throws the `NULL` rows away, which quietly turns "
    "your left join back into an inner join. Put such a condition in the `ON` clause when unmatched rows "
    "must survive.",
    "The number of result rows follows from the data, not from the keyword. If the key is unique on one "
    "side, each row of the other side matches at most once and the join cannot multiply rows. If the key "
    "repeats on both sides, every combination appears: two customers sharing a wrongly reused id and three "
    "orders with it produce six rows. When a join returns more rows than you expected, check the key for "
    "duplicates before you check anything else. When it returns fewer, ask which rows had no partner and "
    "whether you meant to keep them.",
    "A practical routine helps. First say in a sentence which rows the answer must contain: one per order, "
    "or one per customer including those with none. That sentence picks the join. Then name the key and "
    "check that it is unique on the side you believe is unique. Write the join with short table aliases, "
    "qualify every column, and count the rows before you add aggregates. A count that surprises you is "
    "cheap to investigate now and expensive to explain after the report has gone out.",
]


WORKED_EXAMPLE = [
    "Here is the routine on a real question: which customers spent nothing last month? The answer must "
    "contain one row per customer, including those with no orders at all, so the customer table has to stay "
    "whole. That sentence already rules out an inner join. The key is `customer_id`, unique in customers and "
    "repeated in orders, so each customer can meet many orders and the join will return at least one row "
    "per customer.",
    "The first draft reads: customers left join orders on the key, where the order date falls in last month, "
    "group by customer, keep the groups whose total is zero. It returns nothing. The date condition sits in "
    "`WHERE`, and for a customer without orders the order date is `NULL`, so the condition is not true and "
    "the row is gone before the grouping starts. The customers we are looking for were removed by our own "
    "filter.",
    "The fix is to move the date condition into the `ON` clause. Now the join looks for last month's orders "
    "only, and a customer who has none still gets a row with empty order columns. Summing an empty set of "
    "totals gives `NULL`, not zero, so the final test is written with `COALESCE(SUM(o.total), 0) = 0`. The "
    "query now returns customers who never ordered, customers who ordered only in other months, and "
    "customers whose orders last month add up to nothing.",
    "Check the result the cheap way before trusting it. Count the customers in the table and count the rows "
    "the query produces before the final filter: the two numbers must be equal, because the join was meant "
    "to keep every customer exactly once per group. If the second number is smaller, a filter is eating "
    "unmatched rows. If you counted before grouping and it is larger, that is expected, because a customer "
    "with several orders appears once per order until the grouping folds them together.",
    "To sum up: a join pairs rows through a key; an inner join keeps matched pairs only; a left join keeps "
    "every row of the first table and pads the rest with `NULL`; a filter on the padded side belongs in `ON` "
    "when unmatched rows must survive; and the number of rows you get is decided by how often the key "
    "repeats. Say which rows the answer needs, pick the join from that sentence, and count before you "
    "aggregate.",
]


def lesson(title: str = "Inner and left joins", *, long: bool = False) -> dict[str, Any]:
    """A short lesson (about 590 words), or with the worked example a medium one (about 1000 words)."""
    extra: list[dict[str, Any]] = []
    if long:
        extra = [
            {"type": "heading", "level": 2, "text": "A worked example"},
            *[{"type": "paragraph", "text": p} for p in WORKED_EXAMPLE],
        ]
    return {
        "title": title,
        "est_minutes": 9 if long else 6,
        "blocks": [
            {"type": "heading", "level": 1, "text": title},
            *[{"type": "paragraph", "text": p} for p in LESSON_PARAGRAPHS[:3]],
            {
                "type": "code",
                "language": "sql",
                "text": "SELECT c.name, o.total\nFROM customers AS c\nLEFT JOIN orders AS o ON o.customer_id = c.id;",
                "caption": "Every customer, with their orders when they have any",
            },
            *[{"type": "paragraph", "text": p} for p in LESSON_PARAGRAPHS[3:]],
            *extra,
        ],
    }


def _question(
    prompt: str,
    options: list[str],
    answer: int,
    kind: str,
    level: int,
    concept: str,
    hints: list[str],
    whys: list[str],
    explanation: str,
) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "options": [{"id": "abcd"[i], "text": t} for i, t in enumerate(options)],
        "answer": "abcd"[answer],
        "kind": kind,
        "level": level,
        "concept": concept,
        "revisit": "Reading, the part on unmatched rows",
        "hints": hints,
        "rationales": [{"id": "abcd"[i], "why": w} for i, w in enumerate(whys)],
        "explanation": explanation,
    }


QUESTIONS: list[dict[str, Any]] = [
    _question(
        "A report must list every customer with the number of orders they placed, including customers who have never ordered. Which query shape gives that?",
        [
            "customers INNER JOIN orders, then COUNT(*)",
            "customers LEFT JOIN orders, then COUNT(o.id)",
            "orders LEFT JOIN customers, then COUNT(*)",
            "customers CROSS JOIN orders, then COUNT(o.id)",
        ],
        1,
        "scenario",
        2,
        "keeping unmatched rows",
        [
            "Which table must appear in full?",
            "Customers without orders need a row of their own, and it must count as zero.",
            "Start from customers, keep them all, and count a column that is empty when nothing matched.",
        ],
        [
            "It drops customers with no orders, so they are missing from the report.",
            "Every customer is kept, and counting an order column gives 0 where nothing matched.",
            "It keeps every order, not every customer: customers without orders still vanish.",
            "It pairs each customer with every order of the shop, so the counts are meaningless.",
        ],
        "Only a join that keeps the whole customer table returns customers without orders. Counting a column from the orders side then yields 0 for them, where COUNT(*) would count the padded row as 1.",
    ),
    _question(
        "After joining orders to order_items on order_id, SUM(o.total) is far higher than the sum over the orders table alone. What is the most likely cause?",
        [
            "The join dropped orders without items",
            "Each order row is repeated once per item",
            "SUM ignores NULL totals after a join",
            "The ON clause compared the wrong types",
        ],
        1,
        "debug",
        3,
        "joins can multiply rows",
        [
            "Compare the row count before and after the join.",
            "How many result rows does one order with four items produce?",
            "The order's total is added once for each of its items.",
        ],
        [
            "Dropping rows would make the sum smaller, not larger.",
            "An order with several items appears several times, and its total is summed each time.",
            "Ignoring NULLs can only lower a sum.",
            "A type problem would give an error or no matches, not an inflated total.",
        ],
        "A join repeats a row once per matching partner. Summing a column of the repeated side counts it several times; aggregate before joining, or sum a column of the detail table instead.",
    ),
    _question(
        "You left join customers to orders and add WHERE o.status = 'paid'. Customers without any order disappear from the result. Why?",
        [
            "LEFT JOIN never keeps unmatched rows",
            "The filter runs before the join starts",
            "NULL = 'paid' is not true, so they are filtered",
            "The status column is not part of the key",
        ],
        2,
        "debug",
        3,
        "filters after an outer join",
        [
            "What do the order columns contain for a customer with no orders?",
            "The WHERE clause is applied to the joined rows.",
            "Compare an empty value with 'paid' and see whether the row can pass.",
        ],
        [
            "Keeping unmatched rows of the first table is exactly what a left join does.",
            "WHERE is evaluated after the join has produced its rows.",
            "Unmatched customers have NULL in o.status, the comparison is not true, and WHERE removes them.",
            "A condition does not need to be on the key to filter rows.",
        ],
        "Unmatched rows carry NULL in every column of the right table. A WHERE condition on such a column is never true for them, so the outer join behaves like an inner join. Put the condition in ON to keep them.",
    ),
    _question(
        "Which question can an inner join between products and reviews answer correctly on its own?",
        [
            "Which products have no reviews yet?",
            "What is the average rating per reviewed product?",
            "How many products does the shop list?",
            "Which products were never rated above 3?",
        ],
        1,
        "compare",
        2,
        "what an inner join returns",
        [
            "Think about which products are absent from the joined rows.",
            "Three of these need products that have no review at all.",
            "Pick the one that only concerns products with at least one review.",
        ],
        [
            "Products without reviews are exactly the rows this join leaves out.",
            "Only reviewed products are needed, and those are the rows the join returns.",
            "Unreviewed products would be missing from the count.",
            "A product with no reviews was never rated above 3 either, and it would be missing.",
        ],
        "An inner join returns only rows with a partner on both sides. It suits questions about matched pairs and fails for questions that must also see the unmatched rows.",
    ),
    _question(
        "customers has 100 rows and orders has 250 rows; 20 customers have no orders and every order has a valid customer. How many rows does customers LEFT JOIN orders return?",
        ["100", "250", "270", "350"],
        2,
        "apply",
        2,
        "row counts of a left join",
        [
            "Count matched pairs first, then the rows that had no partner.",
            "Each order pairs with exactly one customer.",
            "All the orders, plus one padded row for each customer without any.",
        ],
        [
            "That is one row per customer, but customers with several orders appear several times.",
            "That counts the matched pairs only and forgets the customers without orders.",
            "250 matched rows plus 20 customers kept with empty order columns.",
            "The tables are not added together: a matched customer does not get an extra row.",
        ],
        "A left join returns every matched pair plus one row for each left row without a match: 250 + 20 = 270.",
    ),
    _question(
        "What does an inner join on customer_id do with an order whose customer_id is NULL?",
        [
            "Matches it to every customer",
            "Leaves it out of the result",
            "Keeps it with empty customer columns",
            "Stops with an error",
        ],
        1,
        "recall",
        1,
        "NULL keys never match",
        [
            "Can an unknown value be equal to anything?",
            "The ON condition must be true for a pair to be kept.",
            "No customer satisfies the comparison, and this join keeps no unmatched rows.",
        ],
        [
            "NULL is not a wildcard; it equals nothing, not everything.",
            "The comparison is never true for NULL, so the order finds no partner and is dropped.",
            "Keeping unmatched rows is what an outer join does.",
            "Comparing with NULL is legal; it just is not true.",
        ],
        "A NULL key matches nothing because NULL = x is never true. An inner join therefore drops the row; an outer join from the orders side would keep it.",
    ),
    _question(
        "To find customers who have never ordered, you write customers LEFT JOIN orders. Which condition finishes the query?",
        ["WHERE o.id IS NULL", "WHERE o.id = NULL", "WHERE c.id IS NULL", "ON o.id IS NULL"],
        0,
        "apply",
        2,
        "finding missing rows",
        [
            "What marks a customer row that found no order?",
            "Look at a column of the orders side that is never empty for a real order.",
            "Test that column for emptiness with the operator made for it, after the join.",
        ],
        [
            "Unmatched customers have NULL in the order's id, and IS NULL selects exactly those rows.",
            "= NULL is never true, so this returns no rows at all.",
            "The customer's own id is never empty, so nothing is selected.",
            "In ON it changes which orders match instead of filtering the joined rows.",
        ],
        "After a left join, rows without a partner have NULL in the right table's columns. Testing a never-empty column such as the primary key with IS NULL keeps only those rows.",
    ),
    _question(
        "Two tables are joined on a column that holds duplicate values on both sides. What happens to the result?",
        [
            "Duplicates are removed automatically",
            "Only the first match of each row is kept",
            "Every matching combination appears",
            "The database refuses the join",
        ],
        2,
        "recall",
        2,
        "many-to-many joins",
        [
            "Try it with two rows on one side and three on the other, all with the same value.",
            "Each left row pairs with each right row that has its value.",
            "Two times three pairs.",
        ],
        [
            "A join never removes duplicates; that takes DISTINCT or GROUP BY.",
            "There is no notion of a first match: all partners are returned.",
            "Each row pairs with every partner, so n rows meet m rows in n times m results.",
            "Joining on a non-unique column is allowed, which is why it is a common source of errors.",
        ],
        "Join results are built from all matching pairs. When the key repeats on both sides the pairs multiply, which inflates counts and sums.",
    ),
]


def bank(request: Request) -> dict[str, Any]:
    """The bank a prompt asks for, from the real questions (cycled, so every lesson gets distinct ones)."""
    text = "\n".join(m.content for m in request.messages)
    wanted = re.search(r"Write (\d+) single-lesson questions", text)
    single = int(wanted[1]) if wanted else 8
    cross = int(m[1]) if (m := re.search(r"and (\d+) cross-lesson questions", text)) else 0
    own_part = text.split("Objectives of this lesson:\n", 1)[1].split("\n\n", 1)[0]
    own = re.findall(r"^- ([a-z0-9._-]+):", own_part, re.MULTILINE)
    partner_part = (
        text.split("Partner lessons", 1)[1].split("Lesson:\n")[0] if "Partner lessons" in text else ""
    )
    partners = [c for c in re.findall(r"^- ([a-z0-9._-]+):", partner_part, re.MULTILINE) if c not in own]
    seen = text.split("Existing questions (do not repeat):", 1)[1] if "Existing questions" in text else ""
    fresh = [q for q in QUESTIONS if q["prompt"] not in seen]
    n_cross = min(cross, 2, max(0, len(fresh) - 1)) if partners else 0
    singles = fresh[: len(fresh) - n_cross][:single]
    out = [q | {"objective_codes": [own[i % len(own)]]} for i, q in enumerate(singles)]
    for i, q in enumerate(fresh[len(fresh) - n_cross :] if n_cross else []):
        out.append(q | {"objective_codes": [own[0], partners[i % len(partners)]], "kind": "scenario"})
    return {"questions": out}


def install(llm: Any) -> None:
    """Make a FakeLLM answer the tree, lesson and review bank stages with the realistic content."""
    default = llm.default

    def realistic(stage: str, request: Request) -> Any:
        if stage == "tree":
            return tree()
        if stage == "lesson":
            text = "\n".join(m.content for m in request.messages)
            m = re.search(r"^Lesson: (.+)$", text, re.MULTILINE)
            lo = re.search(r"Write (\d+) to \d+ words", text)
            return lesson(
                m[1].strip() if m else "Inner and left joins", long=lo is not None and int(lo[1]) >= 900
            )
        if stage == "review_bank":
            return bank(request)
        return default(stage, request)

    llm.default = realistic
