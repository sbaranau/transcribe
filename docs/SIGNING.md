# Signing the Windows installer and publishing it to winget

Windows SmartScreen warns about the installer ("Publisher: Unknown", "isn't commonly downloaded")
because it is not code-signed, and an unsigned file has to earn reputation again with every
version. Two free steps fix this; both are prepared in
[windows-release.yml](../.github/workflows/windows-release.yml) and stay off until they are set
up, so releases keep working meanwhile.

| Step | What it gives | Switched on by |
|---|---|---|
| SignPath Foundation | the installer is signed with a certificate by SignPath Foundation (free for open-source projects) | repository variable `SIGNPATH_ORGANIZATION_ID` |
| winget | `winget install sbaranau.LiveTranscription` installs it without the browser's download warning | repository variable `WINGET_ENABLED` = `true` |

Not usable here: Azure Artifact Signing (individuals only in the US and Canada), a self-signed
certificate (SmartScreen treats it like no signature). A paid alternative is Certum's Open Source
Code Signing (about EUR 49 a year, the maintainer's name as publisher).

## 1. SignPath Foundation

Done by the maintainer; nothing here can be done by a tool on their behalf.

1. Turn on two-factor authentication for the GitHub account (SignPath requires it for everyone
   in the project).
2. Apply at <https://signpath.org/apply> with the repository URL. The project page already has
   the required [Code signing policy](../README.md#code-signing-policy) section (attribution,
   roles, privacy).
3. Once accepted, in SignPath:
   - link the trusted build system **GitHub.com** to the project;
   - create the artifact configuration from
     [windows/signpath-artifact-configuration.xml](../windows/signpath-artifact-configuration.xml);
   - create a signing policy for releases, with yourself as approver;
   - create an API token for a user who may submit signing requests.
4. In GitHub, repository **Settings → Secrets and variables → Actions**:
   - secret `SIGNPATH_API_TOKEN`: the API token;
   - variables `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`,
     `SIGNPATH_SIGNING_POLICY_SLUG`, `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG`: the values from
     SignPath.
5. From then on every tagged release waits in the workflow (up to one hour) until you approve
   its signing request in SignPath; the release then gets the signed installer. Without approval
   the step fails and no installer is published for that tag.

Rules from SignPath Foundation's terms that this project keeps: only installers built by this
repository's workflow from a public tag are signed; all bundled components are open source (the
NVIDIA libraries and the models are downloaded on first start, not bundled); product name and
version are the same in every build of a version; the installer can be uninstalled.

## 2. winget

1. Fork <https://github.com/microsoft/winget-pkgs> to your account (the action pushes its
   branches there).
2. Create a classic personal access token with the scopes `public_repo` and `workflow`
   (fine-grained tokens are not supported by the action) and store it as the repository secret
   `WINGET_TOKEN`.
3. Submit the first version by hand with [Komac](https://github.com/russellbanks/Komac):

   ```
   winget install RussellBanks.Komac
   komac token add
   komac new sbaranau.LiveTranscription
   ```

   Give it the installer URL of the latest release
   (`https://github.com/sbaranau/transcribe/releases/download/vX.Y/Live-Transcription-Windows-x64-vX.Y-Setup.exe`).
   Komac reads the rest from the Inno Setup installer (per-user, x64, silent switches). Microsoft
   checks the submission automatically (antivirus scans, silent install and uninstall), and a
   moderator may review it.
4. When it is merged, set the repository variable `WINGET_ENABLED` to `true`. Every later tagged
   release then opens the pull request for its new version by itself.

Only installs through winget avoid the warning; a download in the browser still shows it until
the installer is signed.
