# Research Report

Research ID: `RES-20260828T091313Z-0BB5566B`

Default: Backblaze Computer Backup is the simplest economic choice for one Mac with 2 TB at 99 USD/year and effectively unlimited endpoint storage. It supports encryption, version history and mailed-media restore. However, current reports include repeated Restore app crashes during a 2 TB macOS recovery. Therefore the recommendation is conditional on a successful staged restore test with the current client.

Choose Arq with your own B2/S3-compatible storage if end-to-end encryption control and exit portability matter more than simplicity. Arq 7 lets you keep the storage account independent of the backup app, but billing, egress, retention and restore operations become your responsibility.

Neither replaces a local offline copy. Keep 3-2-1 coverage, test a 50-100 GB restore immediately, document encryption-key recovery, then perform a full restore drill before declaring the backup ready.
