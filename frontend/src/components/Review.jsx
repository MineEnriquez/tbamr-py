import React from 'react'
import { api } from '../api.js'
import { Chip, Rationale } from './common.jsx'
import { RawLink } from './Raw.jsx'

const GRADE = { 0: 'Grading not reported', 1: 'Group 1 · Assoc. w/ R', 2: 'Group 2 · Assoc. w/ R (interim)', 3: 'Group 3 · Uncertain', 5: 'Group 5 · Not assoc. w/ R' }

export default function Review({ st, act, who, openSample }) {
  const fs = st.samples.flatMap(s => s.findings).filter(f => f.review !== 'Not required')
  if (!fs.length) return <div className="panel"><p className="muted">The queue fills after Stage 5: uncertain gradings, low depth, minor variants and discordance wait here for the TB Microbiologist.</p></div>
  return (
    <>
      <p className="muted">Only the TB Microbiologist can change scientific review status. The Evidence Analyst's note is an AI draft to help the reviewer, never a decision.</p>
      <div className="team">{fs.map(f => (
        <div className="panel" key={f.fid} style={{ gap: 10 }}>
          <div className="row between"><button className="btn small ghost mono" onClick={() => openSample(f.sample_id)}>{f.sample_id}</button><Chip label={f.review} kind={f.review.split(' ')[0]} /></div>
          <h3><span className="mono">{f.gene} {f.change}</span> · {f.drug}</h3>
          <dl className="kv"><dt>Grading</dt><dd>{GRADE[f.grade] || f.confidence}</dd><dt>Depth</dt><dd>{f.depth ?? 'n/a'} reads{f.freq < 1 ? ` · ${Math.round(f.freq * 100)}% of reads` : ''}</dd><dt>Why here</dt><dd>{f.reason}</dd></dl>
          {f.interpretation && <div className="box note"><span className="eyebrow">Evidence Analyst note · AI draft</span><p style={{ fontSize: '.88rem' }}>{f.interpretation}</p></div>}
          {f.review === 'Pending'
            ? <Rationale id={'r-' + f.fid} placeholder="e.g. Borderline rpoB mutation; DST can miss it." buttons={[['Reviewed', 'Supports resistance', true], ['Not supported', 'Not supported'], ['Needs more data', 'Needs more data']]}
              extra={<RawLink kind="tbprofiler" k={f.sample_id} />}
              onSubmit={(d, r) => act(() => api.review({ ...who, fid: f.fid, decision: d, rationale: r }), 'Review recorded')} />
            : <p style={{ fontSize: '.86rem' }}><b>{f.reviewer}:</b> {f.rationale}</p>}
        </div>))}</div>
    </>
  )
}
