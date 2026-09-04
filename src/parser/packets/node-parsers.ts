import { type DiagnosticCollector, DiagnosticCode } from '../../diagnostics.js';
import { type XmlElement } from '../xml/nodes.js';
import { AttributeReader, MalformedElementError } from './attributes.js';
import {
  type BaseReplayPacket,
  type BlockPacket,
  type ChangeEntityPacket,
  type ChoiceEntry,
  type ChoicesPacket,
  type ChosenEntitiesPacket,
  type DeckCard,
  type DeckList,
  type FullEntityPacket,
  type GameEntityPacket,
  type HideEntityPacket,
  type MetaDataInfo,
  type MetaDataPacket,
  type OptionEntry,
  type OptionsPacket,
  type OptionTarget,
  type PlayerPacket,
  type ReplayPacket,
  ReplayPacketType,
  type SendChoicesPacket,
  type SendOptionPacket,
  type ShowEntityPacket,
  type ShuffleDeckPacket,
  type SubOptionEntry,
  type SubSpellPacket,
  type SubSpellTarget,
  type TagChangePacket,
  type TagPair,
  type UnknownPacket,
} from './types.js';

/** What a node parser needs from the packetizer that drives it. */
export interface NodeParseContext {
  readonly diagnostics: DiagnosticCollector;
  /** Index already assigned to the packet being built. */
  readonly index: number;
  /** Converts child elements of a container into packets, assigning them indexes. */
  packetizeChildren(elements: readonly XmlElement[]): ReplayPacket[];
}

/**
 * Every packet-specific field, each of which may be `undefined` when absent.
 * Forces parsers to account for every field of the packet explicitly.
 */
type Fields<P extends ReplayPacket> = {
  [K in Exclude<keyof P, keyof BaseReplayPacket>]-?: P[K] | undefined;
};

function build<P extends ReplayPacket>(
  type: P['type'],
  reader: AttributeReader,
  index: number,
  fields: Fields<P>,
  unknownChildren: readonly XmlElement[] = [],
): P {
  const packet: Record<string, unknown> = { index, type };
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined) packet[key] = value;
  }
  const ts = reader.optionalString('ts');
  if (ts !== undefined) packet.ts = ts;
  const unknownAttributes = reader.unknown();
  if (unknownAttributes) packet.unknownAttributes = unknownAttributes;
  if (unknownChildren.length > 0) packet.unknownChildren = unknownChildren;
  return packet as unknown as P;
}

/**
 * Splits the children of a payload element into the elements the caller
 * handles and the ones it does not. Unexpected children are reported and
 * returned so the packet can keep them.
 */
function partitionChildren(
  element: XmlElement,
  ctx: NodeParseContext,
  accepted: ReadonlySet<string>,
): { known: XmlElement[]; unknown: XmlElement[] } {
  const known: XmlElement[] = [];
  const unknown: XmlElement[] = [];
  for (const child of element.children) {
    if (accepted.has(child.name)) {
      known.push(child);
    } else {
      unknown.push(child);
      ctx.diagnostics.violation(
        DiagnosticCode.UNEXPECTED_CHILD,
        `unexpected <${child.name}> inside <${element.name}>`,
        { packetIndex: ctx.index, line: child.line, column: child.column },
      );
    }
  }
  return { known, unknown };
}

/**
 * Parses payload children (`Tag`, `Choice`, `Info`, …) one by one. A malformed
 * item is reported, moved to `unknown` and skipped rather than failing the
 * whole packet.
 */
function parsePayload<T>(
  element: XmlElement,
  ctx: NodeParseContext,
  accepted: ReadonlySet<string>,
  parseItem: (reader: AttributeReader, child: XmlElement) => T,
): { items: T[]; unknown: XmlElement[] } {
  const { known, unknown } = partitionChildren(element, ctx, accepted);
  const items: T[] = [];
  for (const child of known) {
    const reader = new AttributeReader(child, ctx.diagnostics, ctx.index);
    try {
      items.push(parseItem(reader, child));
    } catch (error) {
      if (!(error instanceof MalformedElementError)) throw error;
      unknown.push(child);
      ctx.diagnostics.error(DiagnosticCode.MALFORMED_PACKET, error.message, reader.context());
    }
  }
  return { items, unknown };
}

const TAG_CHILDREN = new Set(['Tag']);
const PLAYER_CHILDREN = new Set(['Tag', 'Deck']);
const CHOICE_CHILDREN = new Set(['Choice']);
const INFO_CHILDREN = new Set(['Info']);
const OPTION_CHILDREN = new Set(['Option']);
const OPTION_ITEM_CHILDREN = new Set(['SubOption', 'Target']);
const TARGET_CHILDREN = new Set(['Target']);
const CARD_CHILDREN = new Set(['Card']);
const SUB_SPELL_PAYLOAD = 'SubSpellTarget';

function readTagPair(reader: AttributeReader): TagPair {
  const pair = { tag: reader.int('tag'), value: reader.int('value') };
  reader.unknown();
  return pair;
}

function readTags(
  element: XmlElement,
  ctx: NodeParseContext,
  accepted: ReadonlySet<string> = TAG_CHILDREN,
): { tags: TagPair[]; unknown: XmlElement[] } {
  const { items, unknown } = parsePayload(element, ctx, accepted, readTagPair);
  return { tags: items, unknown };
}

function readChoices(
  element: XmlElement,
  ctx: NodeParseContext,
): {
  choices: ChoiceEntry[];
  unknown: XmlElement[];
} {
  const { items, unknown } = parsePayload(element, ctx, CHOICE_CHILDREN, (reader) => {
    const entity = reader.entity('entity');
    const index = reader.optionalInt('index');
    reader.unknown();
    return index === undefined ? { entity } : { index, entity };
  });
  return { choices: items, unknown };
}

export function parseGameEntity(element: XmlElement, ctx: NodeParseContext): GameEntityPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const id = reader.int('id');
  const { tags, unknown } = readTags(element, ctx);
  return build<GameEntityPacket>(
    ReplayPacketType.GAME_ENTITY,
    reader,
    ctx.index,
    { id, tags },
    unknown,
  );
}

function parseDeck(element: XmlElement, ctx: NodeParseContext): DeckList {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const type = reader.optionalInt('type');
  reader.unknown();
  const { items } = parsePayload(element, ctx, CARD_CHILDREN, (card): DeckCard => {
    const entry = {
      id: card.string('id'),
      count: card.optionalInt('count') ?? 1,
      premium: card.optionalInt('premium') ?? 0,
    };
    card.unknown();
    return entry;
  });
  return type === undefined ? { cards: items } : { type, cards: items };
}

export function parsePlayer(element: XmlElement, ctx: NodeParseContext): PlayerPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const id = reader.int('id');
  const playerId = reader.int('playerID');
  const name = reader.optionalString('name');
  const accountHi = reader.optionalString('accountHi');
  const accountLo = reader.optionalString('accountLo');
  const rank = reader.optionalInt('rank');
  const legendRank = reader.optionalInt('legendRank');
  const cardback = reader.optionalInt('cardback');

  const { known, unknown } = partitionChildren(element, ctx, PLAYER_CHILDREN);
  const tags: TagPair[] = [];
  let deck: DeckList | undefined;
  for (const child of known) {
    if (child.name === 'Deck') {
      deck = parseDeck(child, ctx);
      continue;
    }
    const tagReader = new AttributeReader(child, ctx.diagnostics, ctx.index);
    try {
      tags.push(readTagPair(tagReader));
    } catch (error) {
      if (!(error instanceof MalformedElementError)) throw error;
      unknown.push(child);
      ctx.diagnostics.error(DiagnosticCode.MALFORMED_PACKET, error.message, tagReader.context());
    }
  }

  return build<PlayerPacket>(
    ReplayPacketType.PLAYER,
    reader,
    ctx.index,
    { id, playerId, name, accountHi, accountLo, rank, legendRank, cardback, deck, tags },
    unknown,
  );
}

export function parseFullEntity(element: XmlElement, ctx: NodeParseContext): FullEntityPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const id = reader.int('id');
  const cardId = reader.optionalString('cardID');
  const { tags, unknown } = readTags(element, ctx);
  return build<FullEntityPacket>(
    ReplayPacketType.FULL_ENTITY,
    reader,
    ctx.index,
    { id, cardId, tags },
    unknown,
  );
}

export function parseShowEntity(element: XmlElement, ctx: NodeParseContext): ShowEntityPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const entity = reader.entity('entity');
  const cardId = reader.optionalString('cardID');
  const { tags, unknown } = readTags(element, ctx);
  return build<ShowEntityPacket>(
    ReplayPacketType.SHOW_ENTITY,
    reader,
    ctx.index,
    { entity, cardId, tags },
    unknown,
  );
}

export function parseChangeEntity(element: XmlElement, ctx: NodeParseContext): ChangeEntityPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const entity = reader.entity('entity');
  const cardId = reader.optionalString('cardID');
  const { tags, unknown } = readTags(element, ctx);
  return build<ChangeEntityPacket>(
    ReplayPacketType.CHANGE_ENTITY,
    reader,
    ctx.index,
    { entity, cardId, tags },
    unknown,
  );
}

export function parseHideEntity(element: XmlElement, ctx: NodeParseContext): HideEntityPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const entity = reader.entity('entity');
  const zone = reader.int('zone');
  const { unknown } = partitionChildren(element, ctx, new Set());
  return build<HideEntityPacket>(
    ReplayPacketType.HIDE_ENTITY,
    reader,
    ctx.index,
    { entity, zone },
    unknown,
  );
}

export function parseTagChange(element: XmlElement, ctx: NodeParseContext): TagChangePacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const entity = reader.entity('entity');
  const tag = reader.int('tag');
  const value = reader.int('value');
  const hasChangeDef = reader.optionalBool('hasChangeDef');
  const { unknown } = partitionChildren(element, ctx, new Set());
  return build<TagChangePacket>(
    ReplayPacketType.TAG_CHANGE,
    reader,
    ctx.index,
    { entity, tag, value, hasChangeDef },
    unknown,
  );
}

export function parseBlock(element: XmlElement, ctx: NodeParseContext): BlockPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const entity = reader.entity('entity');
  const blockType = reader.int('type');
  const actionIndex = reader.optionalInt('index');
  const effectCardId = reader.optionalString('effectCardId');
  const effectIndex = reader.optionalInt('effectIndex');
  const target = reader.optionalEntity('target');
  const subOption = reader.optionalInt('subOption');
  const triggerKeyword = reader.optionalInt('triggerKeyword');
  const children = ctx.packetizeChildren(element.children);
  return build<BlockPacket>(ReplayPacketType.BLOCK, reader, ctx.index, {
    entity,
    blockType,
    actionIndex,
    effectCardId,
    effectIndex,
    target,
    subOption,
    triggerKeyword,
    children,
  });
}

export function parseSubSpell(element: XmlElement, ctx: NodeParseContext): SubSpellPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const spellPrefabGuid = reader.optionalString('spellPrefabGuid');
  const source = reader.optionalEntity('source');
  const targetCount = reader.optionalInt('targetCount');

  const targetElements: XmlElement[] = [];
  const packetElements: XmlElement[] = [];
  for (const child of element.children) {
    (child.name === SUB_SPELL_PAYLOAD ? targetElements : packetElements).push(child);
  }
  const { items: targets, unknown } = parsePayload(
    { ...element, children: targetElements },
    ctx,
    new Set([SUB_SPELL_PAYLOAD]),
    (target): SubSpellTarget => {
      const entry = { index: target.int('index'), entity: target.entity('entity') };
      target.unknown();
      return entry;
    },
  );
  const children = ctx.packetizeChildren(packetElements);
  return build<SubSpellPacket>(
    ReplayPacketType.SUB_SPELL,
    reader,
    ctx.index,
    { spellPrefabGuid, source, targetCount, targets, children },
    unknown,
  );
}

export function parseMetaData(element: XmlElement, ctx: NodeParseContext): MetaDataPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const meta = reader.int('meta');
  const data = reader.optionalInt('data') ?? 0;
  // The DTD calls this attribute `info`; current exporters write `infoCount`.
  const infoCount = reader.optionalInt('infoCount') ?? reader.optionalInt('info');
  const { items: info, unknown } = parsePayload(
    element,
    ctx,
    INFO_CHILDREN,
    (item): MetaDataInfo => {
      const entity = item.entity('entity');
      const index = item.optionalInt('index');
      item.unknown();
      return index === undefined ? { entity } : { index, entity };
    },
  );
  return build<MetaDataPacket>(
    ReplayPacketType.META_DATA,
    reader,
    ctx.index,
    { meta, data, infoCount, info },
    unknown,
  );
}

export function parseChoices(element: XmlElement, ctx: NodeParseContext): ChoicesPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const id = reader.int('id');
  const entity = reader.entity('entity');
  const taskList = reader.optionalInt('taskList');
  const choiceType = reader.int('type');
  const min = reader.int('min');
  const max = reader.int('max');
  const source = reader.entity('source');
  const { choices, unknown } = readChoices(element, ctx);
  return build<ChoicesPacket>(
    ReplayPacketType.CHOICES,
    reader,
    ctx.index,
    { id, entity, taskList, choiceType, min, max, source, choices },
    unknown,
  );
}

export function parseChosenEntities(
  element: XmlElement,
  ctx: NodeParseContext,
): ChosenEntitiesPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const id = reader.int('id');
  const entity = reader.entity('entity');
  const { choices, unknown } = readChoices(element, ctx);
  return build<ChosenEntitiesPacket>(
    ReplayPacketType.CHOSEN_ENTITIES,
    reader,
    ctx.index,
    { id, entity, choices },
    unknown,
  );
}

export function parseSendChoices(element: XmlElement, ctx: NodeParseContext): SendChoicesPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const id = reader.int('id');
  const choiceType = reader.int('type');
  const { choices, unknown } = readChoices(element, ctx);
  return build<SendChoicesPacket>(
    ReplayPacketType.SEND_CHOICES,
    reader,
    ctx.index,
    { id, choiceType, choices },
    unknown,
  );
}

function readTargets(
  element: XmlElement,
  ctx: NodeParseContext,
): { targets: OptionTarget[]; unknown: XmlElement[] } {
  const { items, unknown } = parsePayload(element, ctx, TARGET_CHILDREN, (target): OptionTarget => {
    const entry: OptionTarget = {
      index: target.int('index'),
      entity: target.entity('entity'),
      ...optionalError(target),
    };
    target.unknown();
    return entry;
  });
  return { targets: items, unknown };
}

function optionalError(reader: AttributeReader): { error?: string; errorParam?: number } {
  const error = reader.optionalString('error');
  const errorParam = reader.optionalInt('errorParam');
  const result: { error?: string; errorParam?: number } = {};
  if (error !== undefined) result.error = error;
  if (errorParam !== undefined) result.errorParam = errorParam;
  return result;
}

export function parseOptions(element: XmlElement, ctx: NodeParseContext): OptionsPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const id = reader.int('id');
  const { items: options, unknown } = parsePayload(
    element,
    ctx,
    OPTION_CHILDREN,
    (option, optionElement): OptionEntry => {
      const index = option.int('index');
      const optionType = option.int('type');
      const entity = option.optionalEntity('entity');
      const errors = optionalError(option);
      option.unknown();

      const { known } = partitionChildren(optionElement, ctx, OPTION_ITEM_CHILDREN);
      const subOptionElements = known.filter((child) => child.name === 'SubOption');
      const targetElements = known.filter((child) => child.name === 'Target');
      const { items: subOptions } = parsePayload(
        { ...optionElement, children: subOptionElements },
        ctx,
        new Set(['SubOption']),
        (subOption, subOptionElement): SubOptionEntry => {
          const entry: SubOptionEntry = {
            index: subOption.int('index'),
            entity: subOption.entity('entity'),
            ...optionalError(subOption),
            targets: readTargets(subOptionElement, ctx).targets,
          };
          subOption.unknown();
          return entry;
        },
      );
      const { targets } = readTargets({ ...optionElement, children: targetElements }, ctx);
      return entity === undefined
        ? { index, optionType, ...errors, subOptions, targets }
        : { index, optionType, entity, ...errors, subOptions, targets };
    },
  );
  return build<OptionsPacket>(
    ReplayPacketType.OPTIONS,
    reader,
    ctx.index,
    { id, options },
    unknown,
  );
}

export function parseSendOption(element: XmlElement, ctx: NodeParseContext): SendOptionPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const option = reader.int('option');
  const subOption = reader.optionalInt('subOption');
  const position = reader.optionalInt('position');
  const target = reader.optionalEntity('target');
  const { unknown } = partitionChildren(element, ctx, new Set());
  return build<SendOptionPacket>(
    ReplayPacketType.SEND_OPTION,
    reader,
    ctx.index,
    { option, subOption, position, target },
    unknown,
  );
}

export function parseShuffleDeck(element: XmlElement, ctx: NodeParseContext): ShuffleDeckPacket {
  const reader = new AttributeReader(element, ctx.diagnostics, ctx.index);
  const playerId = reader.int('player_id');
  const { unknown } = partitionChildren(element, ctx, new Set());
  return build<ShuffleDeckPacket>(
    ReplayPacketType.SHUFFLE_DECK,
    reader,
    ctx.index,
    { playerId },
    unknown,
  );
}

export function parseUnknown(element: XmlElement, ctx: NodeParseContext): UnknownPacket {
  const packet: UnknownPacket = {
    index: ctx.index,
    type: ReplayPacketType.UNKNOWN,
    name: element.name,
    attributes: element.attributes,
    children: element.children,
    line: element.line,
    column: element.column,
  };
  const ts = element.attributes.ts;
  return ts === undefined ? packet : { ...packet, ts };
}

export type NodeParser = (element: XmlElement, ctx: NodeParseContext) => ReplayPacket;

/** Element name → parser, for every element that may appear in packet position. */
export const NODE_PARSERS: ReadonlyMap<string, NodeParser> = new Map<string, NodeParser>([
  ['GameEntity', parseGameEntity],
  ['Player', parsePlayer],
  ['FullEntity', parseFullEntity],
  ['ShowEntity', parseShowEntity],
  ['ChangeEntity', parseChangeEntity],
  ['HideEntity', parseHideEntity],
  ['TagChange', parseTagChange],
  ['Block', parseBlock],
  ['SubSpell', parseSubSpell],
  ['MetaData', parseMetaData],
  ['Choices', parseChoices],
  ['ChosenEntities', parseChosenEntities],
  ['SendChoices', parseSendChoices],
  ['Options', parseOptions],
  ['SendOption', parseSendOption],
  ['ShuffleDeck', parseShuffleDeck],
]);
