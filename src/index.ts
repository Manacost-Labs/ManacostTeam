export { parseReplay, parseReplayDocument } from './parse-replay.js';
export { parseReplayStream, streamReplay } from './parser/stream.js';
export type { ReplayStreamChunk, ReplayStreamEvent, ReplayStreamSource } from './parser/stream.js';
export type { DocumentHeader } from './parser/metadata.js';
export * from './semantic/index.js';
export type {
  GameMetadata,
  ParseReplayOptions,
  Replay,
  ReplayDocument,
  ReplayMetadata,
  ReplayPlayer,
} from './replay.js';

export { ReplayError, ReplayParseError, ReplayValidationError } from './errors.js';
export type { ReplayErrorContext, ReplayErrorOptions } from './errors.js';

export { DiagnosticCode } from './diagnostics.js';
export type { DiagnosticLevel, ReplayDiagnostic } from './diagnostics.js';

export { ReplayPacketType, isContainerPacket } from './parser/packets/types.js';
export type {
  BaseReplayPacket,
  BlockPacket,
  ChangeEntityPacket,
  ChoiceEntry,
  ChoicesPacket,
  ChosenEntitiesPacket,
  ContainerPacket,
  DeckCard,
  DeckList,
  FullEntityPacket,
  GameEntityPacket,
  HideEntityPacket,
  MetaDataInfo,
  MetaDataPacket,
  OptionEntry,
  OptionsPacket,
  OptionTarget,
  PlayerPacket,
  ReplayPacket,
  SendChoicesPacket,
  SendOptionPacket,
  ShowEntityPacket,
  ShuffleDeckPacket,
  SubOptionEntry,
  SubSpellPacket,
  SubSpellTarget,
  TagChangePacket,
  TagPair,
  UnknownPacket,
} from './parser/packets/types.js';
export {
  entityId,
  entityRefFromId,
  formatEntityRef,
  parseEntityRef,
} from './parser/packets/entity-ref.js';
export type { EntityIdRef, EntityNameRef, EntityRef } from './parser/packets/entity-ref.js';
export { flattenPackets, walkPackets } from './parser/packets/walk.js';
export type { PacketVisit } from './parser/packets/walk.js';
export type { XmlDocument, XmlElement } from './parser/xml/nodes.js';
export { XmlTreeBuilder, parseXml } from './parser/xml/parser.js';
export type { XmlParseOptions, XmlTreeHooks } from './parser/xml/parser.js';

export { CardType, GameTag, Zone, createTagRegistry, defaultTagRegistry } from './tags/game-tag.js';
export type { CardTypeId, GameTagId, GameTagName, TagRegistry, ZoneId } from './tags/game-tag.js';

export {
  createEntity,
  getCardType,
  getController,
  getTag,
  getZone,
  getZonePosition,
} from './state/entity.js';
export type { Entity, PlayerInfo } from './state/entity.js';
export { EntityStore } from './state/entity-store.js';
export { GameState, applyPacket, applyPackets, createGameState } from './state/engine.js';
export { restoreState, snapshotState } from './state/snapshot.js';
export type { EntitySnapshot, GameStateSnapshot } from './state/snapshot.js';
export { ReplayTimeline, createTimeline } from './state/timeline.js';
export type { TimelineOptions } from './state/timeline.js';
export { collectTagHistory } from './state/tag-history.js';
export type { TagHistory, TagHistoryFilter, TagValueRecord } from './state/tag-history.js';
export {
  BlockType,
  ChoiceType,
  FormatType,
  GameEntityState,
  GameType,
  MetaDataType,
  MulliganState,
  OptionType,
  PlayState,
  Step,
  TAG_VALUE_ENUMS,
  describeTagValue,
  enumName,
} from './tags/enums.js';
export type { EnumTable } from './tags/enums.js';
