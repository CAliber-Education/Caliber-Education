export type MCQLevel = "FINAL" | "INTERMEDIATE" | "FOUNDATION";
export type PricingDuration = "1_month" | "3_months" | "6_months" | "1_year";

export interface DurationPriceMap {
  "1_month": number;
  "3_months": number;
  "6_months": number;
  "1_year": number;
}

export interface MCQSubject {
  id: string;
  level: MCQLevel;
  groupName: string; // "Group I" | "Group II" | "All"
  name: string;
  code: string;
  description: string;
  prices: DurationPriceMap;
  isPopular?: boolean;
  testCount?: number;
  questionCount?: number;
  accentGradient?: string;
}

export interface MCQBundle {
  id: string;
  title: string;
  level: MCQLevel;
  groupName: string;
  subjectIds: string[];
  prices: DurationPriceMap;
  badge?: string;
  isCustom?: boolean;
}

export const DURATION_LABELS: Record<PricingDuration, { label: string; tag: string; discountText?: string }> = {
  "1_month": { label: "1 Month", tag: "Flexible", discountText: "Standard Rate" },
  "3_months": { label: "3 Months", tag: "Popular", discountText: "Save ~20%" },
  "6_months": { label: "6 Months", tag: "Value", discountText: "Save ~35%" },
  "1_year": { label: "1 Year", tag: "Best Value", discountText: "Save ~50%" },
};

// ─── INITIAL PRICING MATRIX ──────────────────────────────────────────────────

// Data is now exclusively fetched from the FastApi Backend using /api/mcq/packages
// This guarantees the database is the source of truth for pricing.

export const INITIAL_MCQ_SUBJECTS: MCQSubject[] = [];

export const INITIAL_MCQ_BUNDLES: MCQBundle[] = [];

// ─── CART & SMART UPSELL CALCULATION ENGINE ─────────────────────────────────

export interface SmartUpsellData {
  type: "group_upgrade" | "both_groups_upgrade" | "custom_bundle";
  group: string;
  bundleId: string;
  bundleTitle: string;
  subjectIds: string[];
  bundlePrice: number;
  originalSum: number;
  savings: number;
  message: string;
}

export interface MCQCartCalculation {
  level: MCQLevel;
  duration: PricingDuration;
  selectedSubjectIds: string[];
  realTotalPrice: number;
  discountedPrice: number;
  savingsAmount: number;
  savingsPercentage: number;
  appliedBundle?: MCQBundle;
  upsellRecommendation?: SmartUpsellData;
}

// Levels shown as "Coming soon" on the MCQ page: no subjects, bundles or
// checkout. Papers, the editor and everything behind them are unchanged.
// To launch a level, remove it from this list.
export const MCQ_COMING_SOON_LEVELS: MCQLevel[] = ["FINAL", "INTERMEDIATE"];

// Display name for a stored group code. Foundation has no groups ("NONE"),
// so its subjects show no group chip and its bundle reads "CA Foundation".
export function mcqGroupLabel(groupName: string): string {
  switch (groupName) {
    case "GROUP_1": return "Group I";
    case "GROUP_2": return "Group II";
    case "BOTH": return "Both Groups";
    case "NONE":
    case "All": return "CA Foundation";
    default: return groupName;
  }
}

export function hasGroupChip(groupName: string): boolean {
  return groupName !== "All" && groupName !== "NONE" && groupName !== "";
}

export function normalizeMCQSubject(raw: any): MCQSubject {
  return {
    id: raw.id || "",
    level: ((raw.level || "FINAL").toUpperCase()) as MCQLevel,
    groupName: raw.groupName || raw.group_name || "All",
    name: raw.name || "",
    code: raw.code || "",
    description: raw.description || "",
    prices: raw.prices || { "1_month": 99, "3_months": 200, "6_months": 300, "1_year": 400 },
    isPopular: raw.isPopular ?? raw.is_popular ?? false,
    testCount: raw.testCount ?? raw.test_count ?? 15,
    questionCount: raw.questionCount ?? raw.question_count ?? 450,
    accentGradient: raw.accentGradient ?? raw.accent_gradient ?? "from-blue-500/20 via-indigo-500/10 to-transparent",
  };
}

export function normalizeMCQBundle(raw: any): MCQBundle {
  return {
    id: raw.id || "",
    title: raw.title || "",
    level: ((raw.level || "FINAL").toUpperCase()) as MCQLevel,
    groupName: raw.groupName || raw.group_name || "All",
    subjectIds: raw.subjectIds || raw.subject_ids || [],
    prices: raw.prices || { "1_month": 250, "3_months": 500, "6_months": 800, "1_year": 1000 },
    badge: raw.badge || "",
    isCustom: raw.isCustom ?? raw.is_custom ?? false,
  };
}

export function calculateMCQCartPrice(
  level: MCQLevel,
  selectedSubjectIds: string[],
  duration: PricingDuration = "1_month",
  customSubjects: MCQSubject[] = INITIAL_MCQ_SUBJECTS,
  customBundles: MCQBundle[] = INITIAL_MCQ_BUNDLES
): MCQCartCalculation {
  const normSubs = (customSubjects || []).map(normalizeMCQSubject);
  const normBundles = (customBundles || []).map(normalizeMCQBundle);

  const levelSubjects = normSubs.filter((s) => s.level === level);
  const subMap = new Map(levelSubjects.map((s) => [s.id, s]));
  const selected = selectedSubjectIds.map((id) => subMap.get(id)).filter(Boolean) as MCQSubject[];

  // Sum of individual selected subjects
  const realTotal = selected.reduce((sum, s) => sum + (s.prices?.[duration] || 0), 0);

  // Check matching bundles
  const selectedSet = new Set(selectedSubjectIds);
  const levelBundles = normBundles.filter((b) => b.level === level);

  let discountedPrice = realTotal;
  let bestBundle: MCQBundle | undefined = undefined;

  for (const b of levelBundles) {
    const bSubIds = b.subjectIds || [];
    const bundleSet = new Set(bSubIds);
    if (bundleSet.size > 0 && Array.from(bundleSet).every((id) => selectedSet.has(id))) {
      const bPrice = b.prices?.[duration] || 0;
      // Remaining subjects
      const remainingIds = selectedSubjectIds.filter((id) => !bundleSet.has(id));
      const remPrice = remainingIds.reduce((sum, id) => {
        const s = subMap.get(id);
        return sum + (s?.prices?.[duration] || 0);
      }, 0);
      const totalCandidate = bPrice + remPrice;

      if (totalCandidate < discountedPrice) {
        discountedPrice = totalCandidate;
        bestBundle = b;
      }
    }
  }

  const savings = Math.max(0, realTotal - discountedPrice);
  const savingsPct = realTotal > 0 ? Math.round((savings / realTotal) * 100) : 0;

  // Smart Upsell Logic
  let upsell: SmartUpsellData | undefined = undefined;

  if (selected.length > 0 && selected.length < levelSubjects.length) {
    const firstSub = selected[0];
    const group = firstSub.groupName;
    const groupSubjects = levelSubjects.filter((s) => s.groupName === group || group === "All");
    const groupSubIds = new Set(groupSubjects.map((s) => s.id));

    // If user has not selected the entire group, recommend the Group Bundle
    if (!Array.from(groupSubIds).every((id) => selectedSet.has(id))) {
      const gBundle = levelBundles.find((b) => b.groupName === group);
      if (gBundle) {
        const bPrice = gBundle.prices?.[duration] || 0;
        const fullBaseSum = groupSubjects.reduce((sum, s) => sum + (s.prices?.[duration] || 0), 0);
        upsell = {
          type: "group_upgrade",
          group: group,
          bundleId: gBundle.id,
          bundleTitle: gBundle.title,
          subjectIds: gBundle.subjectIds || [],
          bundlePrice: bPrice,
          originalSum: fullBaseSum,
          savings: Math.max(0, fullBaseSum - bPrice),
          message: `Get all ${mcqGroupLabel(group)} subjects for just ₹${bPrice}${duration === "1_month" ? "/mo" : ""} (Normally ₹${fullBaseSum})`,
        };
      }
    } else if (level !== "FOUNDATION" && selectedSet.size < levelSubjects.length) {
      // User has selected full Group 1 or full Group 2, recommend Both Groups Super Bundle
      const bothBundle = levelBundles.find((b) => b.groupName === "Both Groups");
      if (bothBundle) {
        const bPrice = bothBundle.prices?.[duration] || 0;
        const fullBaseSum = levelSubjects.reduce((sum, s) => sum + (s.prices?.[duration] || 0), 0);
        upsell = {
          type: "both_groups_upgrade",
          group: "Both Groups",
          bundleId: bothBundle.id,
          bundleTitle: bothBundle.title,
          subjectIds: bothBundle.subjectIds || [],
          bundlePrice: bPrice,
          originalSum: fullBaseSum,
          savings: Math.max(0, fullBaseSum - bPrice),
          message: `Upgrade to Both Groups Super Bundle for just ₹${bPrice}${duration === "1_month" ? "/mo" : ""} (Normally ₹${fullBaseSum})`,
        };
      }
    }
  }

  return {
    level,
    duration,
    selectedSubjectIds,
    realTotalPrice: realTotal,
    discountedPrice,
    savingsAmount: savings,
    savingsPercentage: savingsPct,
    appliedBundle: bestBundle,
    upsellRecommendation: upsell,
  };
}
