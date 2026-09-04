import {Composition} from "remotion";
import {AfterimageJudge} from "./video";

export const Root: React.FC = () => (
  <Composition
    id="AfterimageJudge"
    component={AfterimageJudge}
    durationInFrames={1920}
    fps={30}
    width={1920}
    height={1080}
  />
);
