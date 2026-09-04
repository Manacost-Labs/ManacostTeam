/**
 * The inference rules of the semantic layer, in one place. Every emitted
 * event names the rule that produced it, so each rule can be audited and
 * tested on its own. Sources describe exactly what in the raw packets the
 * rule reads; nothing else is consulted.
 */
export type SemanticEvidenceLevel = 'observed' | 'derived' | 'heuristic';

export interface SemanticEvidence {
  readonly level: SemanticEvidenceLevel;
  readonly rule: SemanticRuleId;
  /** Packets the conclusion rests on. Always contains the event's own `packetIndex`. */
  readonly packetIndices: readonly number[];
}

export const SemanticRuleId = {
  GAME_STARTED: 'GAME_STARTED',
  GAME_ENDED: 'GAME_ENDED',
  GAME_RESET: 'GAME_RESET',
  TURN_STARTED: 'TURN_STARTED',
  CHOICE_OFFERED: 'CHOICE_OFFERED',
  CHOICE_MADE: 'CHOICE_MADE',
  OPTION_CHOSEN: 'OPTION_CHOSEN',
  CARD_PLAYED: 'CARD_PLAYED',
  HERO_POWER_USED: 'HERO_POWER_USED',
  ATTACK: 'ATTACK',
  ZONE_CHANGED: 'ZONE_CHANGED',
  CARD_DRAWN: 'CARD_DRAWN',
  ENTITY_DIED: 'ENTITY_DIED',
  DAMAGE: 'DAMAGE',
  DAMAGE_SOURCE: 'DAMAGE_SOURCE',
  HEALING: 'HEALING',
  HEALING_SOURCE: 'HEALING_SOURCE',
  TRIGGERED: 'TRIGGERED',
  FATIGUE: 'FATIGUE',
  CONCEDED: 'CONCEDED',
} as const;

export type SemanticRuleId = (typeof SemanticRuleId)[keyof typeof SemanticRuleId];

export interface SemanticRule {
  readonly id: SemanticRuleId;
  readonly level: SemanticEvidenceLevel;
  /** What in the raw packets the rule reads. */
  readonly source: string;
  /** Known limits of the rule. */
  readonly caveats?: string;
}

export const SEMANTIC_RULES: Readonly<Record<SemanticRuleId, SemanticRule>> = {
  GAME_STARTED: {
    id: 'GAME_STARTED',
    level: 'observed',
    source: 'GAME_ENTITY packet.',
  },
  GAME_ENDED: {
    id: 'GAME_ENDED',
    level: 'derived',
    source:
      "TAG_CHANGE of STATE to COMPLETE on the game entity; winners/losers read from the players' PLAYSTATE at that moment.",
    caveats: 'Truncated logs never reach STATE=COMPLETE and produce no GAME_ENDED.',
  },
  GAME_RESET: {
    id: 'GAME_RESET',
    level: 'observed',
    source: 'BLOCK of type GAME_RESET.',
    caveats:
      'After a reset entities are re-defined and TURN can decrease; TURN_STARTED is still reported as the log says.',
  },
  TURN_STARTED: {
    id: 'TURN_STARTED',
    level: 'derived',
    source:
      'TAG_CHANGE of TURN on the game entity; the player is whoever has CURRENT_PLAYER=1 once the change is applied.',
    caveats:
      'The player may be missing when CURRENT_PLAYER is set after TURN (not seen in the corpus).',
  },
  CHOICE_OFFERED: { id: 'CHOICE_OFFERED', level: 'observed', source: 'CHOICES packet.' },
  CHOICE_MADE: {
    id: 'CHOICE_MADE',
    level: 'observed',
    source:
      'CHOSEN_ENTITIES packet; the choice type is copied from the CHOICES packet with the same id when one was seen.',
  },
  OPTION_CHOSEN: {
    id: 'OPTION_CHOSEN',
    level: 'derived',
    source: 'SEND_OPTION packet resolved against the most recent OPTIONS packet by option index.',
    caveats: 'Only present for the player whose client wrote the log.',
  },
  CARD_PLAYED: {
    id: 'CARD_PLAYED',
    level: 'derived',
    source:
      'BLOCK of type PLAY whose entity is not a hero power once the block has been applied; target from the block attribute; initiator is "player" for a top-level block and "effect" for a nested one.',
    caveats:
      'The card type is unknown when the entity is never revealed; the event is still emitted with cardType undefined.',
  },
  HERO_POWER_USED: {
    id: 'HERO_POWER_USED',
    level: 'derived',
    source:
      'BLOCK of type PLAY whose entity has CARDTYPE = HERO_POWER once the block has been applied.',
  },
  ATTACK: {
    id: 'ATTACK',
    level: 'derived',
    source:
      'BLOCK of type ATTACK; target from the block attribute, defender from the entity whose DEFENDING tag becomes 1 inside the block.',
    caveats: 'target and defender differ when the attack is redirected; either may be absent.',
  },
  ZONE_CHANGED: {
    id: 'ZONE_CHANGED',
    level: 'observed',
    source:
      'ZONE tag value differing before and after a TAG_CHANGE, SHOW_ENTITY, CHANGE_ENTITY or HIDE_ENTITY packet.',
  },
  CARD_DRAWN: {
    id: 'CARD_DRAWN',
    level: 'derived',
    source: 'ZONE change DECK → HAND while the game STEP is one of the MAIN_* steps.',
    caveats:
      'Opening-hand dealing and mulligan replacements also move DECK → HAND but happen before MAIN_BEGIN and are deliberately not reported as draws.',
  },
  ENTITY_DIED: {
    id: 'ENTITY_DIED',
    level: 'derived',
    source:
      'ZONE change PLAY → GRAVEYARD of an entity whose CARDTYPE is MINION, HERO, WEAPON or LOCATION.',
    caveats:
      'Spells and enchantments also pass PLAY → GRAVEYARD and are excluded; entities with unknown card type are not reported.',
  },
  DAMAGE: {
    id: 'DAMAGE',
    level: 'observed',
    source:
      'META_DATA of type DAMAGE: amount from data, one event per Info target; blockEntity is the entity of the innermost enclosing block.',
    caveats:
      'No source attribution: the log did not record LAST_AFFECTED_BY for the target in the same block.',
  },
  DAMAGE_SOURCE: {
    id: 'DAMAGE_SOURCE',
    level: 'derived',
    source:
      'META_DATA of type DAMAGE followed, in the same container, by a TAG_CHANGE of LAST_AFFECTED_BY on the target; that value is the source.',
    caveats:
      'In the corpus the enclosing block entity differs from LAST_AFFECTED_BY in about one damage event out of five, which is why the block entity is reported separately as blockEntity.',
  },
  HEALING: {
    id: 'HEALING',
    level: 'observed',
    source:
      'META_DATA of type HEALING: amount from data, one event per Info target; blockEntity is the entity of the innermost enclosing block.',
  },
  HEALING_SOURCE: {
    id: 'HEALING_SOURCE',
    level: 'derived',
    source:
      'META_DATA of type HEALING followed, in the same container, by a TAG_CHANGE of LAST_AFFECTED_BY on the target.',
  },
  TRIGGERED: {
    id: 'TRIGGERED',
    level: 'observed',
    source: 'BLOCK of type TRIGGER carrying a triggerKeyword attribute.',
  },
  FATIGUE: { id: 'FATIGUE', level: 'observed', source: 'BLOCK of type FATIGUE.' },
  CONCEDED: {
    id: 'CONCEDED',
    level: 'observed',
    source: 'TAG_CHANGE of PLAYSTATE to CONCEDED on a player entity.',
  },
};

export function evidence(rule: SemanticRuleId, packetIndices: readonly number[]): SemanticEvidence {
  return { level: SEMANTIC_RULES[rule].level, rule, packetIndices };
}
