# Container security policy

CI and CD run the same `scripts/scan-image.sh` with Trivy v0.76.1.
Both OS and language packages are scanned.

| Finding | Release decision |
|---|---|
| CRITICAL, with or without a fix | Block |
| HIGH with an available fix | Block |
| HIGH without an available fix | Report and allow in this lab |
| Scanner or database error | Block |

The first scan reports all HIGH and CRITICAL findings in the workflow log.
An allowed release may still contain unfixed HIGH findings. This is an
explicit lab risk acceptance, not a clean-image claim or a production
approval. Review the reported findings and rebuild as vendor fixes appear.

pip is used to install and check dependencies during the image build, then
uninstalled from the runtime filesystem together with its vendored copies.
Application dependencies remain installed. This does not protect the build
itself from vulnerabilities in the installer; those require separate
upstream review. Buildx SBOM and provenance attestations remain enabled.
