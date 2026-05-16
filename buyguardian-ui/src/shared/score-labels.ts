type ScoreKey = 'listing' | 'seller' | 'price';

type ScoreBand = 'low' | 'medium' | 'high';

type TrustTier = 'pending' | 'safe' | 'high' | 'medium' | 'low' | 'suspicious';

interface ScoreParts {
  listing: number | null;
  seller: number | null;
  price: number | null;
}

const SCORE_THRESHOLDS = {
  low: 5.1,
  medium: 7,
};

const SCORE_LABELS: Record<'low' | 'medium', Record<ScoreKey, string>> = {
  low: {
    listing: 'Rizičan oglas',
    seller: 'Nepouzdan prodavač',
    price: 'Loš omjer cijene i vrijednosti',
  },
  medium: {
    listing: 'Kvaliteta oglasa je prosječna',
    seller: 'Pripazite na prodavača',
    price: 'Nije najbolja vrijednost',
  },
};

const SCORE_LABEL_DEFAULTS = {
  high: 'Dobra ponuda',
  pending: 'Računanje...',
  suspicious: 'Veoma sumnjiv oglas',
};

const TRUST_COLOR_CLASS: Record<TrustTier, string> = {
  pending: 'trust-pending',
  safe: 'trust-safe',
  high: 'trust-high',
  medium: 'trust-medium',
  low: 'trust-low',
  suspicious: 'trust-low',
};

const TRUST_COLOR_HEX: Record<TrustTier, string> = {
  pending: '#42a5f5',
  safe: '#2e7d32',
  high: '#66bb6a',
  medium: '#ffab40',
  low: '#ff1744',
  suspicious: '#ff1744',
};

function getScoreBand(score: number): ScoreBand {
  if (score < SCORE_THRESHOLDS.low) return 'low';
  if (score < SCORE_THRESHOLDS.medium) return 'medium';
  return 'high';
}

function pickWorstScore(scores: ScoreParts): { key: ScoreKey; score: number } | null {
  let worst: { key: ScoreKey; score: number } | null = null;

  for (const key in scores) {
    const typedKey = key as ScoreKey;
    const value = scores[typedKey];
    if (value === null || value === undefined) continue;

    if (!worst || value < worst.score) {
      worst = { key: typedKey, score: value };
    }
  }

  return worst;
}

function getOverallScoreLabel(scores: ScoreParts, isSuspicious?: boolean): string {
  if (isSuspicious) return SCORE_LABEL_DEFAULTS.suspicious;

  const worst = pickWorstScore(scores);
  if (!worst) return SCORE_LABEL_DEFAULTS.pending;

  const band = getScoreBand(worst.score);
  if (band === 'high') return SCORE_LABEL_DEFAULTS.high;
  return SCORE_LABELS[band][worst.key];
}

function getTrustTier(score: number | null | undefined, isSuspicious?: boolean): TrustTier {
  if (isSuspicious) return 'suspicious';
  if (score === null || score === undefined) return 'pending';
  if (score >= 9) return 'safe';
  if (score >= 7) return 'high';
  if (score >= 5.1) return 'medium';
  return 'low';
}

function getTrustColorClass(score: number | null | undefined, isSuspicious?: boolean): string {
  return TRUST_COLOR_CLASS[getTrustTier(score, isSuspicious)];
}

function getTrustColorHex(score: number | null | undefined, isSuspicious?: boolean): string {
  return TRUST_COLOR_HEX[getTrustTier(score, isSuspicious)];
}

const scoreLabelApi = {
  getOverallScoreLabel,
  getTrustColorClass,
  getTrustColorHex,
};

if (typeof globalThis !== 'undefined') {
  (globalThis as any).BuyGuardianScoreLabels = scoreLabelApi;
}
