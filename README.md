# Flows [![Build Status](https://github.com/Ilhasoft/rapidpro/workflows/CI/badge.svg)](https://github.com/Ilhasoft/rapidpro/actions?query=workflow%3ACI) [![codecov](https://codecov.io/gh/weni-ai/flows/branch/main/graph/badge.svg)](https://codecov.io/gh/weni-ai/flows)

Flows module allows organizations to visually build scalable interactive dialogs in the Weni Platform.

### Stable Versions

The set of versions that make up the latest stable release are:

 * [Flows v7.0.4](https://github.com/weni-ai/flows)
 * [Mailroom v7.0.1](https://github.com/weni-ai/mailroom)
 * [Courier v7.0.0](https://github.com/weni-ai/courier)
 * [Archiver v7.0.0](https://github.com/weni-ai/rp-archiver)
 * [Indexer v7.0.0](https://github.com/weni-ai/rp-indexer)
 * [Android Channel v2.0.0](https://github.com/ilhasoft/android-channel/releases/tag/v2.0.0)
 * [Android Surveyor v13.9.0](https://github.com/ilhasoft/surveyor/releases/tag/v13.9.0)

### Versioning in Flows

Major releases of Flows are made every four months on a set schedule. We target November 1st
as a major release (`v7.0.0`), then March 1st as the first stable dot release (`v7.2.0`) and July 1st
as the second stable dot release (`v7.4.0`). The next November would start the next major release `v8.0.0`.

Unstable releases have odd minor versions, that is versions `v7.1.*` would indicate an unstable or *development*
version of Flows. Generally we recommend staying on stable releases unless you
have experience developing against Flows.

To upgrade from one stable release to the next, you should first install and run the migrations
for the latest stable release you are on, then every stable release afterwards. If you are
on version `v6.0.12` and the latest stable release on the `v6.0` series is `v6.0.14`, you should
first install `v6.0.14` before trying to install the next stable release `v6.2.5`.

Generally we only do bug fixes (patch releases) on stable releases for the first two weeks after we put
out that release. After that you either have to wait for the next stable release or take your
chances with an unstable release.

### Versioning of other Components

Flows depends on other components such as Mailroom and Courier. These are versioned to follow the minor releases of 
Flows but may have patch releases made independently of patches to Flows. Other optional components such as the 
Android applications have their own versioning and release schedules. Each stable release of Flows details which 
version of these dependencies you need to run with it.

## Updating FlowEditor version

```
% npm install @nyaruka/flow-editor@whatever-version --save
```

### Get Involved

To run Flows for development, follow the Quick Start guide at http://rapidpro.github.io/rapidpro/docs/development.

### License

In brief, the Affero license states you can use this source for any project free of charge, but that any changes 
you make to the source code must be available to others. Note that unlike the GPL, the AGPL requires these changes to be 
made public even if you do not redistribute them. If you host a version of Flows, you must make the same source you 
are hosting available for others.

The software is provided under AGPL-3.0. Contributions to this project are accepted under the same license.
