import {TransitionSeries, linearTiming} from "@remotion/transitions";
import {fade} from "@remotion/transitions/fade";
import {CoverScene} from "./scenes/cover";
import {VerdictScene} from "./scenes/verdict";
import {ProofChainScene} from "./scenes/proof-chain";
import {PnlScene} from "./scenes/pnl";
import {JuryScene} from "./scenes/jury";
import {AuthorityScene} from "./scenes/authority";
import {FinishScene} from "./scenes/finish";

export const AfterimageJudge: React.FC = () => (
  <TransitionSeries>
    <TransitionSeries.Sequence durationInFrames={210} name="Cover"><CoverScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({durationInFrames: 15})} />
    <TransitionSeries.Sequence durationInFrames={300} name="Verdict"><VerdictScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({durationInFrames: 15})} />
    <TransitionSeries.Sequence durationInFrames={300} name="Proof chain"><ProofChainScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({durationInFrames: 15})} />
    <TransitionSeries.Sequence durationInFrames={330} name="P and L"><PnlScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({durationInFrames: 15})} />
    <TransitionSeries.Sequence durationInFrames={300} name="Model jury"><JuryScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({durationInFrames: 15})} />
    <TransitionSeries.Sequence durationInFrames={300} name="Authority"><AuthorityScene /></TransitionSeries.Sequence>
    <TransitionSeries.Transition presentation={fade()} timing={linearTiming({durationInFrames: 15})} />
    <TransitionSeries.Sequence durationInFrames={270} name="Finish"><FinishScene /></TransitionSeries.Sequence>
  </TransitionSeries>
);
