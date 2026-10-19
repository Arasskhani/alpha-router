import { sourceHost, type WebSource } from "../../lib/webSources";

/** The pages the web tools searched up or read for an answer, under it: each opens in a new tab. */
export default function WebSourceList({ sources }: { sources: WebSource[] }) {
  return (
    <nav className="alpha-router-msg-sources" aria-label="Sources">
      <span className="alpha-router-msg-sources__label">Sources</span>
      <ol className="alpha-router-msg-sources__list">
        {sources.map((source) => (
          <li key={source.url}>
            <a href={source.url} target="_blank" rel="noopener noreferrer nofollow" title={source.url}>
              <span className="alpha-router-msg-sources__title">{source.title}</span>
              <span className="alpha-router-msg-sources__host">{sourceHost(source.url)}</span>
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
