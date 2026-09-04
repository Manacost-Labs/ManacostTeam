import { fileURLToPath } from 'node:url';

export const FIXTURE_URL = new URL('../test.xml', import.meta.url);
export const FIXTURE_PATH = fileURLToPath(FIXTURE_URL);

/** Wraps game-level XML in a minimal HSReplay document. */
export function wrapGame(body: string, gameAttributes = 'id="1"'): string {
  return `<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE hsreplay SYSTEM "https://hearthsim.info/hsreplay/dtd/hsreplay-1.7.dtd">
<HSReplay build="250339" version="1.7">
  <Game ${gameAttributes}>
${body}
  </Game>
</HSReplay>
`;
}

/** A small but complete game prelude: game entity and two players. */
export const PRELUDE = `
    <GameEntity id="1">
      <Tag tag="202" value="1"/>
      <Tag tag="49" value="1"/>
    </GameEntity>
    <Player id="2" playerID="1" accountHi="144115193835963207" accountLo="124857041" name="Alice#1234">
      <Tag tag="50" value="1"/>
      <Tag tag="202" value="2"/>
    </Player>
    <Player id="3" playerID="2" name="Bob#5678">
      <Deck>
        <Card id="CS2_029"/>
        <Card id="CS2_029" count="2" premium="1"/>
      </Deck>
      <Tag tag="50" value="2"/>
      <Tag tag="202" value="2"/>
    </Player>
`;
