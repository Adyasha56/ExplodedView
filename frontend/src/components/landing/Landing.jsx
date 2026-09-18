import { useNavigate } from 'react-router-dom';
import PipelineDemo from './PipelineDemo';
import './landing.css';

const STACK = ['PyMuPDF', 'pdfplumber', 'OpenCV', 'PaddleOCR', 'Gemini Vision'];

const STEPS = [
  {
    n: '1',
    title: 'Find every callout',
    body: 'Contour detection locates each circled reference number on the diagram. Multiple OCR strategies read the digits inside — vector text, per-circle crops, or Gemini Vision when the page is a low-quality scan.',
    wide: true,
  },
  {
    n: '2',
    title: 'Extract the bill of materials',
    body: "Table structure or OCR pulls every row — part number, description, quantity — whether the BOM is native text or a scanned image.",
    wide: false,
  },
  {
    n: '3',
    title: 'Map callouts to parts',
    body: 'Exact and fuzzy matching join each hotspot to its BOM row. Anything still unresolved goes through one more recovery pass before the result ships.',
    wide: true,
  },
];

export default function Landing() {
  const navigate = useNavigate();
  const launch = (useSample) => navigate(useSample ? '/upload?sample=1' : '/upload');

  return (
    <div className="landing-page">
      <a className="skip-link" href="#main">Skip to content</a>

      <nav className="nav-pill" aria-label="Primary">
        <span className="wordmark">
          <span className="wordmark__dot" aria-hidden="true" />
          ExplodedView
        </span>
        <ul className="nav-pill__links">
          <li><a href="#how-it-works">How it works</a></li>
          <li><a href="#under-the-hood">Under the hood</a></li>
        </ul>
        <button className="btn btn--fill btn--small" onClick={() => launch(false)}>Try it</button>
      </nav>

      <main id="main">
        <section className="hero reveal" style={{ '--i': 0 }}>
          <div className="hero__copy">
            <h1>Every callout, linked to its part automatically.</h1>
            <p className="hero__lede">
              Drop in an exploded-view assembly PDF. ExplodedView finds every callout
              circle, reads the bill of materials, and joins them — so clicking a part
              on the diagram highlights its row, instantly.
            </p>
            <div className="hero__actions">
              <button className="btn btn--fill" onClick={() => launch(false)}>Try it on a PDF</button>
              <a className="btn btn--outline" href="#how-it-works">See how it works</a>
            </div>
            <button className="hero__sample-link" onClick={() => launch(true)}>
              No PDF handy? Try a sample assembly →
            </button>
          </div>
          <div className="hero__demo reveal" style={{ '--i': 1 }}>
            <PipelineDemo />
          </div>
        </section>

        <section id="how-it-works" className="how">
          <h2>How it works</h2>
          <div className="how__list">
            {STEPS.map((step) => (
              <article key={step.n} className={`how__step ${step.wide ? 'is-wide' : 'is-narrow'}`}>
                <h3><span className="how__num">{step.n}</span> {step.title}</h3>
                <p>{step.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="under-the-hood" className="stack">
          <h2>Under the hood</h2>
          <p className="stack__lede">
            No single technique reads every PDF. The pipeline tries several, in
            priority order, and falls back gracefully.
          </p>
          <ul className="stack__tags">
            {STACK.map((tech) => (
              <li key={tech}>{tech}</li>
            ))}
          </ul>
        </section>

        <section className="final-cta">
          <p>Have an exploded-view PDF sitting around?</p>
          <div className="final-cta__actions">
            <button className="btn btn--fill" onClick={() => launch(false)}>Try it on a PDF</button>
            <button className="btn btn--outline" onClick={() => launch(true)}>Try a sample instead</button>
          </div>
        </section>
      </main>

      <footer className="foot-stmt">
        <p className="foot-stmt__line">Stop cross-referencing exploded views by hand.</p>
        <div className="foot-stmt__meta">
          <span className="wordmark wordmark--small">
            <span className="wordmark__dot" aria-hidden="true" />
            ExplodedView
          </span>
          <a
            className="muted"
            href="https://github.com/Adyasha56/ExplodedView"
            target="_blank"
            rel="noreferrer"
          >
            View source
          </a>
        </div>
      </footer>
    </div>
  );
}
