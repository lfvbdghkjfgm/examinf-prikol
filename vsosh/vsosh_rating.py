import sqlite3 as sq


def get_statisticks(
    school: str,
    subject: str = "",
    start_year: int = 2016,
    end_year: int = 2026,
    with_subject: bool = False,
    with_year: bool = False,
) -> dict:
    result = []
    for year in range(start_year, end_year + 1):
        stat = {}
        with sq.connect("vsosh.db") as con:
            cur = con.cursor()
            if subject:
                cur.execute(
                    f"""
                    SELECT * FROM '{year}' WHERE school LIKE ? AND subject LIKE ?""",
                    [f"%{school}%", f"%{subject}%"],
                )
            else:
                cur.execute(
                    f"""
                    SELECT * FROM '{year}' WHERE school LIKE ?""",
                    [f"%{school}%"],
                )

            for _, _, _, _, _, _, subj, status in cur.fetchall():
                if subj not in stat.keys():
                    stat[subj] = [0, 0, 0]
                stat[subj][0] += 1
                if status == "призер":
                    stat[subj][1] += 1
                elif status == "победитель":
                    stat[subj][2] += 1
        result.append(stat)
    if with_subject and not with_year:
        stat = {}
        for st in result:
            for a, b in st.items():
                if a not in stat.keys():
                    stat[a] = [0, 0, 0]
                stat[a][0] += b[0]
                stat[a][1] += b[1]
                stat[a][2] += b[2]
        return stat
    if with_year and not with_subject:
        stat = {}
        for year, st in enumerate(result, start_year):
            stat[year] = [0, 0, 0]
            for a, b in st.items():
                stat[year][0] += b[0]
                stat[year][1] += b[1]
                stat[year][2] += b[2]
        return stat
    if with_year and with_subject:
        stat = {}
        for year, st in enumerate(result, start_year):
            stat[year] = {}
            for a, b in st.items():
                if a not in stat[year].keys():
                    stat[year][a] = [0, 0, 0]
                stat[year][a][0] += b[0]
                stat[year][a][1] += b[1]
                stat[year][a][2] += b[2]
        return stat
    stat = {"member": 0, "priser": 0, "pobed": 0}
    for year, st in enumerate(result, start_year):
        for a, b in st.items():
            stat["member"] += b[0]
            stat["priser"] += b[1]
            stat["pobed"] += b[2]
    return stat

    # order_by:
    # 0 - участники
    # 1 - призеры
    # 2 - победители
    # 3 - дипломы


# [школа, участники, призеры, победители]
def rating(
    order_by: int, start_year: int = 2016, end_year: int = 2026, subject: str = ""
):
    if order_by not in [0, 1, 2, 3]:
        return None
    rating = {}
    for year in range(start_year, end_year + 1):
        with sq.connect("vsosh.db") as con:
            cur = con.cursor()
            if subject:
                cur.execute(
                    f"""
                SELECT * FROM '{year}' WHERE subject=?
                """,
                    [f"%{subject}%"],
                )
            else:
                cur.execute(f"""
                SELECT * FROM '{year}'
                """)
            for _, _, _, _, school, _, _, status in cur.fetchall():
                if school not in rating.keys():
                    rating[school] = [0, 0, 0]
                rating[school][0] += 1
                if status == "призер":
                    rating[school][1] += 1
                elif status == "победитель":
                    rating[school][2] += 1
    rating = [[a] + b for a, b in rating.items()]
    if order_by == 0:
        rating.sort(key=lambda d: -d[1])
    elif order_by == 1:
        rating.sort(key=lambda d: -d[2])
    elif order_by == 2:
        rating.sort(key=lambda d: -d[3])
    elif order_by == 3:
        rating.sort(key=lambda d: -(d[2] + d[3]))
    return rating


r = rating(3)
print(r[:10])

for i, s in enumerate(r):
    if "141" in s[0]:
        print(i, s)
