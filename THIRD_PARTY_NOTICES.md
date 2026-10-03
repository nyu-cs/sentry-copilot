# Third-party and game content

The public repository contains project code, schemas, tests, synthetic graphics, and
game-related catalog/annotation metadata. That metadata includes localized game names,
descriptions, operator/Covenant membership information, and source references; it should
not be described as containing no game text.

Recognition reference images, gameplay recordings, emulator IPC binaries, and private
portrait/icon packs are not distributed in the tracked repository. Local reference packs
belong under `data/private/`, recordings under `local_data/`, and generated artifacts under
`outputs/`; these directories are ignored by Git.

Catalog provenance is recorded in the relevant YAML and companion technical documents,
including [the JP strategy catalog bootstrap](docs/jp-strategy-catalog-bootstrap.md).
PRTS references and resource keys identify external provenance; they do not mean an image
or recording is bundled or that redistribution permission has been established.

[LICENSE](LICENSE) covers project code. It does not grant rights to Arknights content or
other third-party materials. This notice makes no determination about the licensing of
external game metadata or media. Review source terms, attribution requirements, and permissions
manually before redistributing third-party content or publishing derived datasets/media.
