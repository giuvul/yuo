import React from 'react';
import {Composition, staticFile} from 'remotion';
import {Lesson, LessonProps, Timeline} from './Lesson';

// One composition; the timeline (narration) sets the length. The scene module is src/gen/scene.tsx.
export const Root: React.FC = () => (
	<Composition
		id="Lesson"
		component={Lesson}
		width={1920}
		height={1080}
		fps={30}
		durationInFrames={300}
		defaultProps={{timeline: null, probe: false, captions: false} as LessonProps}
		calculateMetadata={async ({props}) => {
			const timeline: Timeline = await (await fetch(staticFile('timeline.json'))).json();
			return {durationInFrames: timeline.durationInFrames, fps: timeline.fps, props: {...props, timeline}};
		}}
	/>
);
