type ScoreBand = {
    label: "None" | "Low" | "Moderate" | "High" | "Critical";
    textClass: string;
    badgeClass: string;
};

function toFiniteScore(score: number): number {
    if (!Number.isFinite(score)) return 0;
    return Math.max(0, Math.min(100, score));
}

export function getScoreBand(score: number): ScoreBand {
    const normalized = toFiniteScore(score);

    if (normalized === 0) {
        return {
            label: "None",
            textClass: "text-emerald-500",
            badgeClass: "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30",
        };
    }

    if (normalized < 20) {
        return {
            label: "Low",
            textClass: "text-lime-400",
            badgeClass: "bg-lime-500/10 text-lime-300 border border-lime-500/30",
        };
    }

    if (normalized < 40) {
        return {
            label: "Moderate",
            textClass: "text-amber-400",
            badgeClass: "bg-amber-500/10 text-amber-300 border border-amber-500/30",
        };
    }

    if (normalized < 70) {
        return {
            label: "High",
            textClass: "text-orange-400",
            badgeClass: "bg-orange-500/10 text-orange-300 border border-orange-500/30",
        };
    }

    return {
        label: "Critical",
        textClass: "text-rose-400",
        badgeClass: "bg-rose-500/10 text-rose-300 border border-rose-500/30",
    };
}