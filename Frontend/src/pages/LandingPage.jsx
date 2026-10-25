import {
  ArrowRight,
  Bot,
  BriefcaseBusiness,
  CalendarCheck,
  Check,
  Code2,
  FileText,
  GraduationCap,
  Headset,
  Languages,
  Mic,
  Sliders,
  TrendingUp,
  Workflow,
} from 'lucide-react'
import { useEffect } from 'react'
import HeroPreview from '../components/landing/HeroPreview.jsx'
import IntroSplash from '../components/landing/IntroSplash.jsx'
import Button from '../components/ui/Button.jsx'

const CAPABILITIES = [
  { icon: Languages, label: 'Multilingual voices: English, Hindi, Hinglish' },
  { icon: Sliders, label: 'Configurable agents' },
  { icon: Workflow, label: 'Flexible workflows (planned)' },
  { icon: Mic, label: 'Browser voice testing' },
]

const FEATURES = [
  {
    icon: Bot,
    title: 'Agent customization',
    status: 'Available',
    text: 'Name each agent, write its instructions, pick its language and speaking speed, and switch it on or off. Changes are saved to your account.',
  },
  {
    icon: Languages,
    title: 'Voice languages',
    status: 'Available',
    text: 'Conversations run in English, Hindi or Hinglish (Hindi written in Latin script), with streaming transcription and spoken replies.',
  },
  {
    icon: FileText,
    title: 'Knowledge and business context',
    status: 'Planned',
    text: 'Upload documents and website content so answers reflect your business. Knowledge ingestion is not connected yet.',
  },
  {
    icon: Mic,
    title: 'Voice testing',
    status: 'Available locally',
    text: 'Talk to the voice pipeline from your browser and watch the transcript, reply and audio playback in real time. Per-agent testing is still being connected.',
  },
]

const USE_CASES = [
  { icon: TrendingUp, title: 'Sales agents', text: 'Qualify leads and answer product questions around the clock.' },
  { icon: Headset, title: 'Customer support', text: 'Handle common questions and hand off the rest to your team.' },
  { icon: CalendarCheck, title: 'Appointment booking', text: 'Book, move and confirm appointments in a natural conversation.' },
  { icon: BriefcaseBusiness, title: 'HR and recruitment', text: 'Run first-round screening calls and answer candidate questions.' },
  { icon: GraduationCap, title: 'Education assistants', text: 'Explain topics and practise speaking with learners.' },
  { icon: Sliders, title: 'Custom agents', text: 'Write your own instructions for any conversation you need.' },
]

const STEPS = [
  { title: 'Create', text: 'Name your agent and say what it is for.' },
  { title: 'Configure', text: 'Write its instructions and choose a language and speed.' },
  { title: 'Test', text: 'Speak or type and review the transcript and replies.' },
  { title: 'Deploy', text: 'Phone numbers and integrations are planned, not available yet.' },
]

// Sample greetings are illustrative text, not recordings.
const LANGUAGES = [
  { name: 'English', sample: 'Hello! How can I help you today?' },
  { name: 'Hindi', sample: 'नमस्ते! मैं आपकी क्या मदद कर सकता हूँ?' },
  { name: 'Hinglish', sample: 'Namaste! Main aapki kya madad kar sakta hoon?' },
]

const API_EXAMPLE = `POST /api/v1/agents
Authorization: Bearer <token>

{
  "name": "Appointment assistant",
  "system_prompt": "You are a friendly receptionist…",
  "language": "en",
  "voice_config": { "speed": 1.0 },
  "is_active": true
}`

function SectionHeading({ eyebrow, title, children, id }) {
  return (
    <div className="section-heading">
      <p className="eyebrow">{eyebrow}</p>
      <h2 id={id}>{title}</h2>
      {children && <p>{children}</p>}
    </div>
  )
}

export default function LandingPage() {
  useEffect(() => {
    document.title = 'AwaazAI · Build voice agents your way'
  }, [])

  return (
    <>
      <IntroSplash />
      <section className="hero" aria-labelledby="hero-title">
        <div className="grid-texture hero-grid" aria-hidden="true" />
        <div className="container hero-inner">
          <div className="hero-copy reveal">
            <p className="eyebrow">AI VOICE AGENTS FOR REAL BUSINESSES</p>
            <h1 id="hero-title">Build voice agents your way.</h1>
            <p className="hero-lede">Design, configure, test, and manage AI voice agents for natural conversations with your customers.</p>
            <div className="hero-actions">
              <Button to="/register" variant="primary" size="lg" icon={ArrowRight}>
                Get Started Free
              </Button>
              <Button to="/voice-test" variant="outline" size="lg">
                Explore the Demo
              </Button>
            </div>
            <ul className="hero-tags" aria-label="Capabilities">
              {CAPABILITIES.map(({ icon: Icon, label }) => (
                <li key={label}>
                  <Icon size={15} aria-hidden="true" />
                  {label}
                </li>
              ))}
            </ul>
          </div>
          <div className="hero-visual reveal" style={{ animationDelay: '120ms' }}>
            <HeroPreview />
          </div>
        </div>
      </section>

      <section className="section" id="product" aria-labelledby="product-title">
        <div className="container">
          <SectionHeading eyebrow="Product" title="Everything you need to shape a voice agent" id="product-title">
            What works today is marked <strong>Available</strong>. Anything still on the roadmap is marked <strong>Planned</strong>.
          </SectionHeading>
          <div className="feature-grid">
            {FEATURES.map(({ icon: Icon, title, status, text }) => (
              <article className="card card-hover feature-card" key={title}>
                <span className="state-icon">
                  <Icon size={22} aria-hidden="true" />
                </span>
                <h3>{title}</h3>
                <p>{text}</p>
                <span className={`badge ${status === 'Planned' ? 'badge-warning' : 'badge-success'}`}>{status}</span>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section" id="languages" aria-labelledby="lang-title">
        <div className="container">
          <SectionHeading eyebrow="Multilingual voice" title="Speak your customers’ language" id="lang-title">
            Voice conversations are available in English, Hindi and Hinglish. More languages are not available yet.
          </SectionHeading>
          <div className="usecase-grid">
            {LANGUAGES.map(({ name, sample }) => (
              <article className="card lang-card" key={name}>
                <span className="badge badge-success">Available</span>
                <h3>{name}</h3>
                <p lang={name === 'Hindi' ? 'hi' : 'en'}>“{sample}”</p>
                <small className="muted">Example greeting</small>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section section-alt" id="knowledge" aria-labelledby="know-title">
        <div className="container dev-grid">
          <div>
            <SectionHeading eyebrow="Knowledge and integrations" title="Give agents your business context" id="know-title">
              Documents, website content and connections to calendars and CRMs are on the roadmap. None of them is available today.
            </SectionHeading>
            <ul className="check-list">
              <li><Check size={16} aria-hidden="true" /><span><strong>Planned:</strong> upload documents and add websites as knowledge sources.</span></li>
              <li><Check size={16} aria-hidden="true" /><span><strong>Planned:</strong> connect calendars, CRMs, helpdesks and webhooks.</span></li>
              <li><Check size={16} aria-hidden="true" /><span><strong>Planned:</strong> phone numbers so customers can call an agent.</span></li>
            </ul>
          </div>
          <div className="card page-stack" style={{ gap: 'var(--space-3)' }}>
            <h3>Prompt-based context today</h3>
            <p className="muted">Until knowledge sources exist, put the facts an agent needs (opening hours, policies, prices) directly in its system prompt.</p>
          </div>
        </div>
      </section>

      <section className="section" id="solutions" aria-labelledby="solutions-title">
        <div className="container">
          <SectionHeading eyebrow="Solutions" title="One platform, many conversations" id="solutions-title">
            Examples of what you can build by writing the right instructions. They are starting points, not ready-made workflows.
          </SectionHeading>
          <div className="usecase-grid">
            {USE_CASES.map(({ icon: Icon, title, text }) => (
              <article className="card card-hover usecase" key={title}>
                <Icon size={22} aria-hidden="true" />
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section section-alt" id="how-it-works" aria-labelledby="how-title">
        <div className="container">
          <SectionHeading eyebrow="How it works" title="From idea to conversation in four steps" id="how-title" />
          <ol className="flow">
            {STEPS.map((step, index) => (
              <li key={step.title}>
                <span className="flow-number">{index + 1}</span>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="section" id="developers" aria-labelledby="dev-title">
        <div className="container dev-grid">
          <div>
            <SectionHeading eyebrow="Developers" title="A straightforward API" id="dev-title">
              Manage agents programmatically with a JSON API secured by bearer tokens. Integrations and deployment options will grow over time.
            </SectionHeading>
            <ul className="check-list">
              <li><Check size={16} aria-hidden="true" /><span><strong>Available:</strong> sign-up, sign-in and owner-scoped agent management over REST.</span></li>
              <li><Check size={16} aria-hidden="true" /><span><strong>Planned:</strong> phone numbers, third-party integrations, webhooks and hosted deployment.</span></li>
            </ul>
          </div>
          <figure className="code-card">
            <figcaption>
              <Code2 size={15} aria-hidden="true" /> Create an agent
            </figcaption>
            <pre>
              <code>{API_EXAMPLE}</code>
            </pre>
          </figure>
        </div>
      </section>

      <section className="section" id="pricing" aria-labelledby="pricing-title">
        <div className="container">
          <div className="card pricing-note">
            <h2 id="pricing-title">Pricing</h2>
            <p>Pricing hasn’t been announced. AwaazAI is in early development, and creating an account is free while we build.</p>
          </div>
        </div>
      </section>

      <section className="section cta-section" aria-labelledby="cta-title">
        <div className="container cta">
          <h2 id="cta-title">Ready to build your first voice agent?</h2>
          <p>Create an account, write your agent’s instructions and try a conversation.</p>
          <div className="hero-actions" style={{ justifyContent: 'center' }}>
            <Button to="/register" variant="primary" size="lg" icon={ArrowRight}>
              Get Started Free
            </Button>
            <Button to="/login" variant="outline" size="lg">
              Sign in
            </Button>
          </div>
        </div>
      </section>
    </>
  )
}
