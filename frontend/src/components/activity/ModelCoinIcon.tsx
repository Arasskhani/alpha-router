type Props = {
  title?: string;
};

export default function ModelCoinIcon({ title }: Props) {
  return (
    <span className="activity-model-coin" title={title}>
      <svg className="activity-model-coin__stack" viewBox="0 0 24 24" role="img" aria-hidden="true">
        <ellipse cx="12" cy="6" rx="6.8" ry="2.5" fill="currentColor" opacity="0.58" />
        <path d="M5.2 6v2.2c0 1.4 3 2.5 6.8 2.5s6.8-1.1 6.8-2.5V6" fill="currentColor" opacity="0.95" />
        <ellipse cx="12" cy="11" rx="6.8" ry="2.5" fill="currentColor" opacity="0.52" />
        <path d="M5.2 11v2.2c0 1.4 3 2.5 6.8 2.5s6.8-1.1 6.8-2.5V11" fill="currentColor" opacity="0.84" />
        <ellipse cx="12" cy="16" rx="6.8" ry="2.5" fill="currentColor" opacity="0.44" />
        <path d="M5.2 16v2.1c0 1.4 3 2.5 6.8 2.5s6.8-1.1 6.8-2.5V16" fill="currentColor" opacity="0.72" />
        <ellipse cx="12" cy="20.6" rx="6.8" ry="2.5" fill="currentColor" opacity="0.36" />
        <path d="M16.8 3.8l3.5 2.1-1.1.6-.3 4-.7-.4.2-3.3-2.3-1.3z" fill="currentColor" opacity="0.9" />
      </svg>
    </span>
  );
}
