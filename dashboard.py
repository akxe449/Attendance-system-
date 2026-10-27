"""
Attendance Dashboard  (Person C)

Run:  streamlit run dashboard.py
Reads attendance.db (create it first with  python seed.py).
Most numbers come straight from the SQL views in schema.sql.
"""
import altair as alt
import pandas as pd
import streamlit as st

import dashboard_data as dd

st.set_page_config(page_title="Attendance Dashboard", page_icon="🎓", layout="wide")

BLUE, GREEN, ORANGE, RED, GREY = "#3b6fd4", "#2e9e6b", "#e8a33d", "#d9534f", "#9aa5b8"

# ---- a little CSS so the cards and tables look neat -------------------------
st.markdown("""
<style>
.block-container {padding-top: 1.6rem;}
div[data-testid="stMetric"] {
    background: #f1f4fa; border-left: 5px solid #3b6fd4;
    padding: 10px 14px; border-radius: 6px;
}
h1, h2, h3 {color: #1f3a6b;}
section[data-testid="stSidebar"] {background: #eef2fa;}
.note {color: #667; font-size: 0.85rem;}
</style>
""", unsafe_allow_html=True)


def need_data():
    st.title("🎓 Attendance Dashboard")
    st.warning("No data found in `attendance.db` yet.")
    st.code("python seed.py", language="bash")
    st.write("Run the command above in the project folder, then refresh this page.")
    st.stop()


def color_pct(v):
    if pd.isna(v):
        return ""
    if v < 75:
        return "background-color: #f8d7d6"
    if v < 85:
        return "background-color: #fdf0d5"
    return "background-color: #d9f0e4"


def pct_table(df, cols=None):
    """Show a dataframe with a progress bar for attendance_pct."""
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "attendance_pct": st.column_config.ProgressColumn(
                "Attendance %", min_value=0, max_value=100, format="%.1f%%"),
            "pct": st.column_config.ProgressColumn(
                "Overall %", min_value=0, max_value=100, format="%.1f%%"),
        },
    )


if not dd.db_ready():
    need_data()

# ---------------------------------------------------------------- sidebar
st.sidebar.title("🎓 Attendance")
st.sidebar.caption("Face Recognition + Anti-Spoofing  \nDBMS mini project")
page = st.sidebar.radio(
    "Go to",
    ["🏠 Overview", "📊 Attendance", "👩‍🎓 Students", "🗓️ Sessions",
     "🛡️ Security", "⚠️ Defaulters & Export", "🗄️ Database"],
)
st.sidebar.markdown("---")
threshold = st.sidebar.slider("Minimum attendance % (defaulter limit)", 50, 100, 75, step=5)
if st.sidebar.button("🔄 Refresh data"):
    st.rerun()
st.sidebar.markdown('<p class="note">Data is read live from attendance.db each time you click around.</p>',
                    unsafe_allow_html=True)

k = dd.kpis(threshold)

# ================================================================ OVERVIEW
if page == "🏠 Overview":
    st.title("Attendance Overview")
    st.caption("A quick look at how the class is doing.")

    c = st.columns(4)
    c[0].metric("Students", k["students"])
    c[1].metric("Courses", k["courses"])
    c[2].metric("Sessions held", k["sessions"])
    c[3].metric("Average attendance", f"{k['avg_pct']:.1f}%")
    c = st.columns(4)
    c[0].metric("Attendance marked", k["marked"])
    c[1].metric("Late arrivals", k["late"])
    c[2].metric(f"Below {threshold}%", k["defaulters"])
    c[3].metric("Spoof attempts caught", k["spoofs"])

    if k["no_face"]:
        st.info(f"{k['no_face']} student(s) have no face samples yet - register them with `register_student.py`.")

    left, right = st.columns([3, 2])

    with left:
        st.subheader("Attendance per day")
        trend = dd.daily_trend()
        if trend.empty:
            st.write("No sessions yet.")
        else:
            line = alt.Chart(trend).mark_line(point=True, strokeWidth=2.5).encode(
                x=alt.X("day:T", title="Date"),
                y=alt.Y("present:Q", title="Students present"),
                color=alt.Color("course_code:N", title="Course"),
                tooltip=["day:T", "course_code", "present", "enrolled"],
            ).properties(height=320)
            st.altair_chart(line, use_container_width=True)

    with right:
        st.subheader("Present vs Late")
        sp = dd.status_split()
        if not sp.empty:
            donut = alt.Chart(sp).mark_arc(innerRadius=60).encode(
                theta="n:Q",
                color=alt.Color("status:N", title="Status",
                                scale=alt.Scale(domain=["Present", "Late"], range=[GREEN, ORANGE])),
                tooltip=["status", "n"],
            ).properties(height=320)
            st.altair_chart(donut, use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Average % by course")
        ca = dd.course_averages()
        base = alt.Chart(ca).encode(
            x=alt.X("course_code:N", title="Course", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("avg_pct:Q", title="Average attendance %", scale=alt.Scale(domain=[0, 100])),
        )
        bars = base.mark_bar(color=BLUE).encode(tooltip=["course_code", "avg_pct", "students"])
        text = base.mark_text(dy=-8).encode(text=alt.Text("avg_pct:Q", format=".1f"))
        rule = alt.Chart(pd.DataFrame({"y": [threshold]})).mark_rule(
            color=RED, strokeDash=[6, 4]).encode(y="y:Q")
        st.altair_chart((bars + text + rule).properties(height=300), use_container_width=True)
        st.caption(f"Red dashed line = {threshold}% limit")

    with right:
        st.subheader("Students ranked by overall %")
        so = dd.student_overall()
        so["zone"] = so["pct"].apply(lambda v: f"below {threshold}%" if v < threshold else "ok")
        chart = alt.Chart(so).mark_bar().encode(
            y=alt.Y("full_name:N", sort="-x", title=None),
            x=alt.X("pct:Q", title="Overall attendance %", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("zone:N", legend=None,
                            scale=alt.Scale(domain=["ok", f"below {threshold}%"], range=[GREEN, RED])),
            tooltip=["roll_no", "full_name", "attended", "total", "pct"],
        ).properties(height=300)
        st.altair_chart(chart, use_container_width=True)

# ================================================================ ATTENDANCE
elif page == "📊 Attendance":
    st.title("Attendance Analysis")
    codes = dd.courses()
    cc = st.columns(2)
    course = cc[0].selectbox("Course", ["All courses"] + codes["course_code"].tolist())
    dept = cc[1].selectbox("Department", ["All departments"] + dd.departments()["dept_name"].tolist())
    sel_course = None if course == "All courses" else course
    sel_dept = None if dept == "All departments" else dept

    tab1, tab2, tab3, tab4 = st.tabs(["Summary table", "Heatmap", "Trends", "Late arrivals"])

    with tab1:
        df = dd.summary(sel_course, sel_dept)
        st.caption("Source: view `v_attendance_summary`")
        pct_table(df.drop(columns=["title"]))
        if not df.empty:
            hist = alt.Chart(df).mark_bar(color=BLUE).encode(
                x=alt.X("attendance_pct:Q", bin=alt.Bin(step=10), title="Attendance % (bucket)"),
                y=alt.Y("count()", title="No. of student-course rows"),
            ).properties(height=250, title="How attendance % is spread")
            st.altair_chart(hist, use_container_width=True)

    with tab2:
        hm_course = sel_course or codes["course_code"].iloc[0]
        if sel_course is None:
            hm_course = st.selectbox("Course for heatmap", codes["course_code"].tolist(), key="hm")
        h = dd.heatmap(hm_course)
        if h.empty:
            st.write("No sessions for this course.")
        else:
            h["day"] = h["day"].astype(str)
            heat = alt.Chart(h).mark_rect(stroke="white", strokeWidth=2).encode(
                x=alt.X("day:O", title="Session date"),
                y=alt.Y("roll_no:N", title=None),
                color=alt.Color("status:N", title="Status",
                                scale=alt.Scale(domain=["Present", "Late", "Absent"],
                                                range=[GREEN, ORANGE, "#e3e6ec"])),
                tooltip=["roll_no", "day", "status"],
            ).properties(height=max(200, 38 * h["roll_no"].nunique()))
            st.altair_chart(heat, use_container_width=True)
            st.caption("Green = present, orange = late, grey = absent. Easy to spot who keeps missing.")

    with tab3:
        a, b = st.columns(2)
        with a:
            st.markdown("**Which weekday has the most check-ins?**")
            wd = dd.by_weekday()
            wd = wd[wd["marked"] > 0]
            st.altair_chart(alt.Chart(wd).mark_bar(color=BLUE).encode(
                x=alt.X("weekday:N", sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], title=None),
                y=alt.Y("marked:Q", title="Attendance marked"),
                tooltip=["weekday", "marked"]).properties(height=280), use_container_width=True)
        with b:
            st.markdown("**Attendance by month**")
            mo = dd.monthly_attendance()
            st.altair_chart(alt.Chart(mo).mark_bar(color=GREEN).encode(
                x=alt.X("month:N", title="Month", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("marked:Q", title="Attendance marked"),
                tooltip=["month", "marked"]).properties(height=280), use_container_width=True)
        st.markdown("**Attendance rate per session** (present / enrolled)")
        tr = dd.daily_trend()
        tr["rate"] = (100.0 * tr["present"] / tr["enrolled"]).round(1)
        st.altair_chart(alt.Chart(tr).mark_area(opacity=0.35, line=True).encode(
            x=alt.X("day:T", title="Date"), y=alt.Y("rate:Q", title="% present", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("course_code:N", title="Course"),
            tooltip=["day:T", "course_code", "present", "enrolled", "rate"]).properties(height=300),
            use_container_width=True)

    with tab4:
        lt = dd.late_by_student()
        st.caption("A student is marked Late by a database trigger if they arrive more than 10 min after start.")
        st.altair_chart(alt.Chart(lt).mark_bar(color=ORANGE).encode(
            x=alt.X("late_count:Q", title="Times late"), y=alt.Y("full_name:N", sort="-x", title=None),
            tooltip=["roll_no", "full_name", "late_count"]).properties(height=320), use_container_width=True)

# ================================================================ STUDENTS
elif page == "👩‍🎓 Students":
    st.title("Students")
    sl = dd.student_list()
    tab1, tab2 = st.tabs(["All students", "Student profile"])

    with tab1:
        q = st.text_input("Search by name or roll no")
        view = sl
        if q:
            m = sl["full_name"].str.contains(q, case=False) | sl["roll_no"].str.contains(q, case=False)
            view = sl[m]
        st.dataframe(view, use_container_width=True, hide_index=True,
                     column_config={"face_samples": st.column_config.ProgressColumn(
                         "Face samples", min_value=0, max_value=5, format="%d")})
        st.caption("Face samples are the saved 128-number face encodings. 5 per student is the target.")

    with tab2:
        who = st.selectbox("Pick a student", sl["roll_no"] + " - " + sl["full_name"])
        roll = who.split(" - ")[0]
        row = sl[sl["roll_no"] == roll].iloc[0]
        c = st.columns(4)
        c[0].metric("Roll no", roll)
        c[1].metric("Department", row["dept_name"].replace("Information Technology", "IT")
                    .replace("Computer Science", "CS"))
        c[2].metric("Semester", int(row["semester"]))
        c[3].metric("Face samples", int(row["face_samples"]))

        sc = dd.student_courses(roll)
        a, b = st.columns([2, 3])
        with a:
            st.markdown("**Per course**")
            pct_table(sc.drop(columns=["title"]))
        with b:
            st.altair_chart(alt.Chart(sc).mark_bar().encode(
                x=alt.X("course_code:N", title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("attendance_pct:Q", title="Attendance %", scale=alt.Scale(domain=[0, 100])),
                color=alt.condition(alt.datum.attendance_pct < threshold,
                                    alt.value(RED), alt.value(GREEN)),
                tooltip=["course_code", "attended", "total_sessions", "attendance_pct"]
            ).properties(height=220), use_container_width=True)
        st.markdown("**Attendance history**")
        st.dataframe(dd.student_history(roll), use_container_width=True, hide_index=True)

# ================================================================ SESSIONS
elif page == "🗓️ Sessions":
    st.title("Sessions")
    ss = dd.sessions()
    st.caption("Source: view `v_session_report`")
    f = st.selectbox("Filter by course", ["All"] + dd.courses()["course_code"].tolist())
    view = ss if f == "All" else ss[ss["course_code"] == f]
    st.dataframe(view, use_container_width=True, hide_index=True)

    st.subheader("Open one session")
    options = [f"#{r.session_id}  {r.course_code}  {r.session_date} {r.start_time}" for r in view.itertuples()]
    if options:
        pick = st.selectbox("Session", options)
        sid = int(pick.split()[0].lstrip("#"))
        row = ss[ss["session_id"] == sid].iloc[0]
        c = st.columns(4)
        c[0].metric("Enrolled", int(row["enrolled"]))
        c[1].metric("Present", int(row["present"]))
        c[2].metric("Absent", int(row["enrolled"] - row["present"]))
        c[3].metric("Spoof attempts", int(row["spoof_attempts"]))

        a, b = st.columns([3, 2])
        with a:
            st.markdown("**Present / Late**")
            st.dataframe(dd.session_present(sid), use_container_width=True, hide_index=True)
        with b:
            st.markdown("**Absent**")
            st.dataframe(dd.session_absent(sid), use_container_width=True, hide_index=True)

# ================================================================ SECURITY
elif page == "🛡️ Security":
    st.title("Anti-Spoofing & Security")
    st.caption("Every failed liveness check is saved in the `spoof_attempt` table.")
    c = st.columns(3)
    c[0].metric("Spoof attempts", k["spoofs"])
    total = max(k["marked"] + k["spoofs"], 1)
    c[1].metric("Attempt rate", f"{100 * k['spoofs'] / total:.1f}%")
    c[2].metric("Real check-ins", k["marked"])

    a, b = st.columns(2)
    with a:
        st.subheader("Attempts by reason")
        r = dd.spoof_by_reason()
        if r.empty:
            st.write("No attempts logged. 🎉")
        else:
            st.altair_chart(alt.Chart(r).mark_bar(color=RED).encode(
                x=alt.X("reason:N", title=None, sort="-y", axis=alt.Axis(labelAngle=-15)),
                y=alt.Y("attempts:Q", title="Attempts"),
                tooltip=["reason", "attempts"]).properties(height=300), use_container_width=True)
    with b:
        st.subheader("Liveness challenges passed")
        cu = dd.challenge_usage()
        if not cu.empty:
            st.altair_chart(alt.Chart(cu).mark_arc(innerRadius=55).encode(
                theta="n:Q", color=alt.Color("challenge:N", title="Challenge"),
                tooltip=["challenge", "n"]).properties(height=300), use_container_width=True)

    a, b = st.columns(2)
    with a:
        st.subheader("Match distance")
        md = dd.match_distances()
        if not md.empty:
            st.altair_chart(alt.Chart(md).mark_bar(color=BLUE).encode(
                x=alt.X("match_distance:Q", bin=alt.Bin(maxbins=15), title="Face distance (lower = better)"),
                y=alt.Y("count()", title="Check-ins")).properties(height=260), use_container_width=True)
            st.caption(f"Average distance: {md['match_distance'].mean():.3f}")
    with b:
        st.subheader("Attempts by course")
        sc = dd.spoof_by_course()
        if not sc.empty:
            st.altair_chart(alt.Chart(sc).mark_bar(color=ORANGE).encode(
                x=alt.X("course_code:N", title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("attempts:Q")).properties(height=260), use_container_width=True)

    st.subheader("Full log")
    st.dataframe(dd.spoof_log(), use_container_width=True, hide_index=True)

# ================================================================ DEFAULTERS
elif page == "⚠️ Defaulters & Export":
    st.title("Defaulters & Export")
    st.caption(f"Students under {threshold}% in at least one course. Change the limit in the sidebar.")
    d = dd.defaulters(threshold)
    if d.empty:
        st.success("Nobody is below the limit 🎉")
    else:
        c = st.columns(3)
        c[0].metric("Rows below limit", len(d))
        c[1].metric("Different students", d["roll_no"].nunique())
        c[2].metric("Lowest %", f"{d['attendance_pct'].min():.1f}%")
        styled = d.style.map(color_pct, subset=["attendance_pct"]) if hasattr(d.style, "map") else d.style.applymap(color_pct, subset=["attendance_pct"])
        st.dataframe(styled,
                     use_container_width=True, hide_index=True)
        st.altair_chart(alt.Chart(d).mark_bar(color=RED).encode(
            x=alt.X("attendance_pct:Q", title="Attendance %", scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("full_name:N", title=None, sort="x"),
            color=alt.Color("course_code:N", title="Course"),
            tooltip=["roll_no", "course_code", "attendance_pct"]).properties(height=300),
            use_container_width=True)

    st.subheader("Download")
    full = dd.summary()
    a, b = st.columns(2)
    a.download_button("⬇️ Full attendance summary (CSV)", full.to_csv(index=False).encode(),
                      "attendance_summary.csv", "text/csv")
    b.download_button("⬇️ Defaulters (CSV)", d.to_csv(index=False).encode(),
                      "defaulters.csv", "text/csv")

# ================================================================ DATABASE
else:
    st.title("Database")
    st.caption("Handy for the viva - shows what is inside attendance.db.")
    tc = dd.table_counts()
    a, b = st.columns([2, 3])
    with a:
        st.dataframe(tc, use_container_width=True, hide_index=True)
    with b:
        st.altair_chart(alt.Chart(tc).mark_bar(color=BLUE).encode(
            y=alt.Y("table:N", sort="-x", title=None), x=alt.X("rows:Q", title="Rows"),
            tooltip=["table", "rows"]).properties(height=300), use_container_width=True)

    st.subheader("What the dashboard uses")
    st.markdown("""
| Page | Reads from |
|---|---|
| Overview, Attendance, Students | view `v_attendance_summary` |
| Defaulters | view `v_defaulters` (75%), or the summary view for other limits |
| Sessions | view `v_session_report` |
| Security | table `spoof_attempt` |
""")
    st.markdown("**Triggers in the DB:** only enrolled students can be marked, only while the session is Open, "
                "and arriving more than 10 minutes late flips the status to Late.")
