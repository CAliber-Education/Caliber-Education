// All India Scholarship Test. Shapes mirror
// edu-platform-backend/app/routers/scholarship.py.

export interface ScholarshipTest {
  id: string;
  title: string;
  description: string;
  level: string;
  price: number;
  durationMinutes: number;
  totalMarks: number;
  questionCount: number;
  resultsPublished: boolean;
}

export interface ScholarshipStatus {
  registered: boolean;
  paymentPending: boolean;
  attempted: boolean;
  resultsPublished: boolean;
}

export interface ScholarshipAttempt {
  paperId: string;
  title: string;
  submittedAt: string;
  resultsPublished: boolean;
}

export interface ScholarshipQuestionResult {
  id: string;
  sectionTitle: string;
  type: string;
  caseNarrative: string;
  text: string;
  options: string[];
  correctOptionIndex: number | null;
  userSelected: number | null;
  status: "correct" | "incorrect" | "skipped";
  marks: number;
  negativeMarks: number;
  marksEarned: number;
  explanation: string;
}

export interface ScholarshipResult {
  paperId: string;
  title: string;
  rank: number;
  score: number;
  totalMarks: number;
  correctCount: number;
  incorrectCount: number;
  skippedCount: number;
  timeSeconds: number;
  publishedAt: string | null;
  questions: ScholarshipQuestionResult[];
}

export interface ScholarshipLeaderboardRow {
  rank: number;
  userId: string;
  name: string;
  email: string;
  phone: string;
  stage: string;
  score: number;
  totalMarks: number;
  correctCount: number;
  incorrectCount: number;
  skippedCount: number;
  timeSeconds: number;
  submittedAt: string | null;
}

export interface AdminScholarshipTest extends ScholarshipTest {
  status: string;
  resultsPublishedAt: string | null;
  attemptCount: number;
}

export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s.toString().padStart(2, "0")}s` : `${s}s`;
}

export function formatMarks(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0$/, "");
}
