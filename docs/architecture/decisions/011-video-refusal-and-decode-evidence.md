# ADR 011: Explicit video refusal and decoded-output evidence

Status: Accepted  
Date: 2026-07-26

## Context

Source passthrough is safe only when timestamp access is qualified and the
stored pixel representation is supported. An FFmpeg process can exit with code
zero after seeking into a truncated file while producing no decoded frame or
audio time. Treating that exit code alone as success would admit damaged media.

## Decision

Representative qualification records FFmpeg progress and requires observable
decoded output:

- video probes must report at least one decoded frame;
- audio probes must report positive decoded output time; and
- timeout, non-zero exit, or zero decoded output is a failure.

Video access plans have a distinct `refused` status. The initial passthrough
policy refuses:

- missing, zero, negative, or malformed video time bases;
- pixel formats outside the policy's explicit supported set; and
- failed representative video decode or timestamp probes.

VFR, rotation metadata, non-square pixel aspect, and unusual but valid positive
time bases are preserved without baking, resampling, or frame-number
addressing. Frame lookup and extraction require an `available` plan.

## Consequences

Damage can no longer pass qualification merely because FFmpeg returned zero.
Policy refusals are machine-readable and distinguishable from sources that
have not yet been qualified. Remux or transcode remediation remains future
work and cannot occur silently.
