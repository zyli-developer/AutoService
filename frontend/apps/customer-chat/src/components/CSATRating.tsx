import { useState } from 'react';
import { useTranslation } from '@autoservice/i18n';
import { useChatStore } from '../store/chatStore';

interface CSATRatingProps {
  onSubmit: (score: number) => void;
}

const LABEL_KEYS: Record<number, string> = {
  1: 'customer.csat.label.1',
  2: 'customer.csat.label.2',
  3: 'customer.csat.label.3',
  4: 'customer.csat.label.4',
  5: 'customer.csat.label.5',
};

export function CSATRating({ onSubmit }: CSATRatingProps) {
  const { t } = useTranslation();
  const csatRequest = useChatStore((s) => s.csatRequest);
  const [hoveredScore, setHoveredScore] = useState<number | null>(null);
  const [selectedScore, setSelectedScore] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!csatRequest) return null;

  // The CSAT prompt may come from the agent (translated server-side) or fall
  // back to a generic question rendered in the user's UI language.
  const prompt = csatRequest.prompt ?? t('customer.csat.prompt');
  const displayScore = hoveredScore ?? selectedScore;

  const handleSubmit = () => {
    if (selectedScore == null) return;
    setSubmitting(true);
    onSubmit(selectedScore);
  };

  return (
    <div className="csat-overlay" data-testid="csat-overlay">
      <div className="csat-card" data-testid="csat-card">
        <p className="csat-prompt">{prompt}</p>
        <div className="csat-stars" role="radiogroup" aria-label={t('customer.csat.rating_aria')}>
          {[1, 2, 3, 4, 5].map((score) => (
            <button
              key={score}
              type="button"
              className={`csat-star${(displayScore ?? 0) >= score ? ' active' : ''}`}
              data-testid={`csat-star-${score}`}
              aria-label={`${score} - ${t(LABEL_KEYS[score])}`}
              onMouseEnter={() => setHoveredScore(score)}
              onMouseLeave={() => setHoveredScore(null)}
              onClick={() => setSelectedScore(score)}
              disabled={submitting}
            >
              <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
              </svg>
            </button>
          ))}
        </div>
        {displayScore != null && (
          <p className="csat-label" data-testid="csat-label">{t(LABEL_KEYS[displayScore])}</p>
        )}
        <button
          type="button"
          className="csat-submit"
          data-testid="csat-submit"
          onClick={handleSubmit}
          disabled={selectedScore == null || submitting}
        >
          {submitting ? t('customer.csat.submitting') : t('customer.csat.submit')}
        </button>
      </div>
    </div>
  );
}
