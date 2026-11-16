// Sample paths for the design catalogue and the graph's tests: no backend, fixed ids, realistic names.
import type { PathOut, ProgressOut, SkillState } from "../api/client";

type SkillSpec = {
  title: string;
  /** titles of the skills this one builds on */
  needs?: string[];
  state?: SkillState;
  mastery?: number;
  /** lesson states, one lesson each (default: one planned lesson) */
  lessons?: string[];
};
type BranchSpec = { title: string; level?: number; skills: SkillSpec[] };

type SamplePath = { path: PathOut; progress: ProgressOut };

const slug = (title: string) => title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

/** Builds a path and its progress from a short description. Skill ids are slugs of the titles. */
export function samplePath(id: string, title: string, spec: BranchSpec[]): SamplePath {
  const skills: ProgressOut["skills"] = {};
  const branches = spec.map((b, bi) => ({
    id: `${id}-b${bi + 1}`,
    code: `B${bi + 1}`,
    title: b.title,
    skills: b.skills.map((s, si) => {
      const skillId = slug(s.title);
      const mastery = s.mastery ?? (s.state === "mastered" ? 0.9 : 0);
      skills[skillId] = { state: s.state ?? "locked", mastery, evidence: mastery > 0 ? 6 : 0 };
      return {
        id: skillId,
        code: `B${bi + 1}.S${si + 1}`,
        title: s.title,
        summary: `What ${s.title.toLowerCase()} are for, and how to use them with confidence.`,
        requires: (s.needs ?? []).map(slug),
        objectives: [
          { id: `${skillId}-o1`, statement: `Say what ${s.title.toLowerCase()} are for` },
          { id: `${skillId}-o2`, statement: `Use ${s.title.toLowerCase()} in a small example` },
        ],
        lessons: (s.lessons ?? ["planned"]).map((state, li) => ({
          id: `${skillId}-l${li + 1}`,
          code: `B${bi + 1}.S${si + 1}.L${li + 1}`,
          kind: "core",
          state,
          title: li === 0 ? `${s.title}: the idea` : `${s.title}: in practice`,
        })),
      };
    }),
  }));
  return {
    path: {
      id,
      title,
      subject: title,
      goal: "",
      status: "active",
      difficulty: "standard",
      content_lang: "en",
      level_check: "done",
      branches,
      jobs: [],
    },
    progress: {
      gamification: "full",
      skills,
      branches: spec.map((b, bi) => ({ id: `${id}-b${bi + 1}`, title: b.title, level: b.level ?? 1, xp: ((b.level ?? 1) - 1) ** 2 * 100 })),
    },
  };
}

/** The brand's own example: five skills on two branches, one of each state. */
export const SMALL_TREE = samplePath("sample-small", "Data structures", [
  {
    title: "Linear structures",
    level: 2,
    skills: [
      { title: "Arrays", state: "mastered", mastery: 1, lessons: ["ready", "ready"] },
      { title: "Linked lists", needs: ["Arrays"], state: "needs_review", mastery: 0.7, lessons: ["ready"] },
      { title: "Hash tables", needs: ["Arrays"], state: "available", lessons: ["planned"] },
    ],
  },
  {
    title: "Branching structures",
    skills: [
      { title: "Trees", needs: ["Linked lists"], state: "in_progress", mastery: 0.62, lessons: ["ready", "generating"] },
      { title: "Graphs", needs: ["Trees", "Hash tables"], state: "locked", lessons: ["planned"] },
    ],
  },
]);

/** A full-size path: five branches, twenty-one skills, prerequisites across branches, every state. */
export const LARGE_TREE = samplePath("sample-large", "SQL for data analysis", [
  {
    title: "Querying basics",
    level: 3,
    skills: [
      { title: "Selecting columns", state: "mastered", mastery: 1, lessons: ["ready", "ready"] },
      { title: "Filtering rows", needs: ["Selecting columns"], state: "mastered", mastery: 0.95, lessons: ["ready", "ready"] },
      { title: "Sorting and limiting", needs: ["Filtering rows"], state: "mastered", mastery: 0.9, lessons: ["ready"] },
      { title: "NULL handling", needs: ["Filtering rows"], state: "needs_review", mastery: 0.72, lessons: ["ready"] },
      { title: "Data types and casting", needs: ["NULL handling"], state: "mastered", mastery: 0.88, lessons: ["ready"] },
    ],
  },
  {
    title: "Combining tables",
    level: 2,
    skills: [
      { title: "Inner joins", needs: ["Filtering rows"], state: "mastered", mastery: 0.85, lessons: ["ready", "ready"] },
      { title: "Outer joins", needs: ["Inner joins", "NULL handling"], state: "in_progress", mastery: 0.55, lessons: ["ready", "generating"] },
      { title: "Self joins", needs: ["Inner joins"], state: "available", lessons: ["ready", "planned"] },
      { title: "Set operations", needs: ["Outer joins"], state: "locked", lessons: ["planned"] },
    ],
  },
  {
    title: "Aggregation",
    level: 2,
    skills: [
      { title: "Aggregate functions", needs: ["Filtering rows"], state: "mastered", mastery: 0.92, lessons: ["ready"] },
      { title: "Grouping with GROUP BY", needs: ["Aggregate functions"], state: "in_progress", mastery: 0.3, lessons: ["ready", "failed"] },
      { title: "Filtering groups with HAVING", needs: ["Grouping with GROUP BY"], state: "locked", lessons: ["planned"] },
      { title: "Pivoting with CASE", needs: ["Grouping with GROUP BY", "NULL handling"], state: "locked", lessons: ["planned"] },
    ],
  },
  {
    title: "Window functions",
    skills: [
      { title: "Ranking functions", needs: ["Grouping with GROUP BY", "Sorting and limiting"], state: "locked", lessons: ["planned"] },
      { title: "Running totals", needs: ["Ranking functions"], state: "locked", lessons: ["planned"] },
      { title: "LAG and LEAD", needs: ["Ranking functions"], state: "locked", lessons: ["planned"] },
      { title: "Window frames", needs: ["Running totals"], state: "locked", lessons: ["planned"] },
    ],
  },
  {
    title: "Structure and speed",
    skills: [
      { title: "Subqueries and CTEs", needs: ["Inner joins"], state: "available", lessons: ["planned"] },
      { title: "Normalisation", needs: ["Subqueries and CTEs"], state: "locked", lessons: ["planned"] },
      { title: "Indexes", needs: ["Normalisation"], state: "locked", lessons: ["planned"] },
      { title: "Reading query plans", needs: ["Indexes", "Outer joins"], state: "locked", lessons: ["planned"] },
    ],
  },
]);
