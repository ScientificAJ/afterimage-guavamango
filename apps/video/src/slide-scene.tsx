import {AbsoluteFill, CanvasImage, Easing, Interactive, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";

export type SlideSceneProps = {
  slide: string;
  eyebrow: string;
  headline: string;
  body: string;
  accent?: "cyan" | "coral" | "amber" | "green";
  align?: "top" | "bottom";
  showCaption?: boolean;
};

const colorFor = (accent: SlideSceneProps["accent"]) => {
  if (accent === "coral") return "#FF7469";
  if (accent === "amber") return "#F4C45D";
  if (accent === "green") return "#69E09C";
  return "#44E5F0";
};

export const SlideScene: React.FC<SlideSceneProps> = ({slide, eyebrow, headline, body, accent = "cyan", align = "bottom", showCaption = true}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const color = colorFor(accent);
  return (
    <AbsoluteFill style={{backgroundColor: "#061218", overflow: "hidden", fontFamily: "Arial, sans-serif"}}>
      <CanvasImage
        src={staticFile(`slides/${slide}`)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          opacity: interpolate(frame, [0, 15, durationInFrames - 18, durationInFrames], [0, 1, 1, 0.88], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.16, 1, 0.3, 1)}),
          scale: interpolate(frame, [0, durationInFrames], [1.025, 1.075], {extrapolateLeft: "clamp", extrapolateRight: "clamp"}),
        }}
      />
      {showCaption ? <>
        <AbsoluteFill style={{background: align === "bottom" ? "linear-gradient(180deg, rgba(2,9,13,0.08) 20%, rgba(2,9,13,0.92) 82%, #02090D 100%)" : "linear-gradient(180deg, #02090D 0%, rgba(2,9,13,0.9) 28%, rgba(2,9,13,0.10) 72%)"}} />
        <Interactive.Div
          name="Narrative caption"
          style={{
            position: "absolute",
            left: 120,
            right: 120,
            top: align === "top" ? 92 : undefined,
            bottom: align === "bottom" ? 88 : undefined,
            opacity: interpolate(frame, [12, 36], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.16, 1, 0.3, 1)}),
            translate: interpolate(frame, [12, 36], ["0px 36px", "0px 0px"], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.bezier(0.16, 1, 0.3, 1)}),
          }}
        >
          <Interactive.Div name="Eyebrow" style={{fontSize: 24, fontWeight: 800, letterSpacing: 3, color, marginBottom: 18}}>{eyebrow}</Interactive.Div>
          <Interactive.Div name="Headline" style={{fontSize: 82, lineHeight: 1.03, fontWeight: 800, color: "#F4FBFC", maxWidth: 1540, letterSpacing: -2}}>{headline}</Interactive.Div>
          <Interactive.Div name="Supporting copy" style={{fontSize: 38, lineHeight: 1.28, fontWeight: 500, color: "#C6D8DC", maxWidth: 1460, marginTop: 22}}>{body}</Interactive.Div>
        </Interactive.Div>
      </> : null}
      <Interactive.Div name="Proof progress" style={{position: "absolute", left: 0, bottom: 0, height: 8, width: `${interpolate(frame, [0, durationInFrames], [0, 100], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})}%`, backgroundColor: color}} />
    </AbsoluteFill>
  );
};
