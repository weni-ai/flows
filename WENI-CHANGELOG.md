1.8.8-rapidpro-7.1.27
----------
* Change in CI, from './manage.py' to 'python manage.py'
* Update verion of weni-rp-apps to 2.4.3

1.8.7-rapidpro-7.1.27
----------
* Add a condition to enable httplog_webhook to a org
* New trigger onboard modal

1.8.6-rapidpro-7.1.27
----------
* Update version of weni-rp-apps to 2.4.2

1.8.5-rapidpro-7.1.27
----------
* Update version of weni-rp-apps to 2.4.1
* Chore: Update FlowEditor to 1.2.1
* fix: add weni prefix to css classes
* Remove iso-639 lib from pip-requires and lock in CI

1.8.4-rapidpro-7.1.27
----------
* Update README to flows build status
* Adjust ticketers errors tests
* Adjust tests in flows
* Resolve errors in flows CI
* Run black in flows
* Update Dockerfile to lock requests version

1.8.3-rapidpro-7.1.27
----------
* Update weni-rp-apps from 2.3.4 to 2.4.0

1.8.2-rapidpro-7.1.27
----------
* Update weni-rp-apps from 2.3.3 to 2.3.4

1.8.1-rapidpro-7.1.27
----------
* Update weni-rp-apps from 2.3.2 to 2.3.3
* Removing the internal ticketer this will no longer be used
* Update release function in external services
* Add contact name filter in ContactEndpoint

1.8.0-rapidpro-7.1.27
----------
* Use Weni Floweditor from package.json

1.7.2-rapidpro-7.1.27
----------
* Update weni-rp-apps from 2.3.0 to 2.3.2
* Remove codecov package from pyproject
* Add read field in serializer of MsgReadSerializer

1.7.1-rapidpro-7.1.27
----------
* Add teams app in temba celery autodiscovery list

1.7.0-rapidpro-7.1.27
----------
* Update weni-rp-apps from 2.2.0 to 2.3.0
* External services support on Weni Flows
* Add endpoint to list type action

1.6.23-rapidpro-7.1.27
----------
* Update weni-rp-apps from 2.1.3 to 2.2.0

1.6.22-rapidpro-7.1.27
----------
* Adds read status in status choices

1.6.21-rapidpro-7.1.27
----------
* Update weni-rp-apps from 2.1.2 to 2.1.3

1.6.20-rapidpro-7.1.27
----------
* Transforms ContactImport model constants into environment variables

1.6.19-rapidpro-7.1.27
----------
* Update gunicorn start

1.6.18-rapidpro-7.1.27
----------
* fix: case removal and reorder on expression and field routers [flow-editor #19](https://github.com/Ilhasoft/floweditor/pull/19)
* fix: change the has_issues field to False, when create flow

1.6.17-rapidpro-7.1.27
----------
* Fix: add weni.s3 to installed_apps

1.6.16-rapidpro-7.1.27
----------
* Revert "fix: add weni.s3 to installed_apps"

1.6.15-rapidpro-7.1.27
----------
* Update weni-rp-apps from 2.0.1 to 2.1.0
* Add activities app on INSTALLED_APPS
* fix: add weni.s3 to installed_apps
* feat: Adjustment in welcome flow

1.6.14-rapidpro-7.1.27
----------
* Add Courier S3 endpoint env key
* Update weni-rp-apps to 2.0.1

1.6.13-rapidpro-7.1.27
----------
* Adds exclusion list of channels that go to integrations
* Update rp-apps to 2.0.0

1.6.12-rapidpro-7.1.27
----------
* Create endpoint that returns success orgs

1.6.11-rapidpro-7.1.27
----------
* Update weni-rp-apps package to support gRPC-REST conversion

1.6.10-rapidpro-7.1.27
----------
* Internal ticketer conditional on org initialize

1.6.9-rapidpro-7.1.27
----------
* Modify contact history request trigger method to `load`

1.6.8-rapidpro-7.1.27
----------
* Add weni-rp-apps orgs_api app

1.6.7-rapidpro-7.1.27
----------
* Weni announcement as billing alert

1.6.6-rapidpro-7.1.27
----------
* Add ticketer name input field on twilioflex connect #380

1.6.5-rapidpro-7.1.27
----------
* Env for `refresh_whatsapp_templates` task time schedule

1.6.4-rapidpro-7.1.27
----------
* Improve `trim_channel_logs_task` performance by splitting the query

1.6.3-rapidpro-7.1.27
----------
* Bump weni-rp-apps from 1.0.28 to 1.0.29
* Locks the Poetry version to 1.1.15 #371

1.6.2-rapidpro-7.1.27
----------
* Improve trim_http_logs_task performance by splitting the query

1.6.1-rapidpro-7.1.27
----------
* Bump weni-rp-apps from 1.0.27 to 1.0.28

1.6.0-rapidpro-7.1.27
----------
* Bump weni-rp-apps from 1.0.26 to 1.0.27
* connect wenichats ticketer integration
* Enable CORS on Rapidpro
* fix: sidemenu padding
* Downgrade Sentry version from 1.9.9 to 1.9.8

1.5.9-rapidpro-7.1.27
----------
* Bump weni-rp-apps from 1.0.25 to 1.0.26

1.5.8-rapidpro-7.1.27
----------
* Remove gcc dependencies from Dockerfile

1.5.7-rapidpro-7.1.27
----------
* Lock dulwich package version into 0.20.45

1.5.6-rapidpro-7.1.27
----------
* Add build dependencies on Dockerfile

1.5.5-rapidpro-7.1.27
----------
* Update gunicorn to support max_requests #348 

1.5.4-rapidpro-7.1.27
----------
* Bump weni-rp-apps from 1.0.24 to 1.0.25

1.5.3-rapidpro-7.1.27
----------
* Adjust weni.internal in INSTALLED_APPS

1.5.2-rapidpro-7.1.27
----------
* Add weni.internals to INSTALLED_APPS

1.5.1-rapidpro-7.1.27
----------
* Bump weni-rp-apps from 1.0.22 to 1.0.23
* add iframe post message on editor load

1.5.0-rapidpro-7.1.27
----------
* Feat: Hide org config fields
* Remove mozilla_django_oidc SessionRefresh middleware
* RocketChat Ticketer out of beta

1.4.0-rapidpro-7.1.27
----------
* Integration support with Microsoft Teams

1.3.5-rapidpro-7.1.27
----------
* Update FB api version to 14.0 to get templates for WhatsApp Cloud
* Redirect advice #325 

1.3.4-rapidpro-7.1.27
----------
* Fix message templates syncing for new categories #321 (Nyaruka refference change api facebook version)

1.3.3-rapidpro-7.1.27
----------
* Fix Facebook channel creation #319 

1.3.2-rapidpro-7.1.27
----------
* Update weni-rp-apps to 1.0.20

1.3.1-rapidpro-7.1.27
----------
* Update weni-rp-apps to 1.0.19

1.3.0-rapidpro-7.1.27
----------
* Update weni-rp-apps to 1.0.18
* WhatsApp Cloud New Channel Feature
* Slack channel

1.2.7-rapidpro-7.1.27
----------
* Link translation using MutationObserver for FlowEditor links

1.2.6-rapidpro-7.1.27
----------
* RapidPro updated to v7.1.27

1.2.6-rapidpro-7.0.4
----------
 * HelpHero iframe event

1.2.5-rapidpro-7.0.4
----------
 * Helphero integration
 * New Sample Flow

1.2.4-rapidpro-7.0.4
----------
 * New Weni announcement
 * Option to disable OIDC Authentication

1.2.3-rapidpro-7.0.4
----------
 * Update weni-rp-apps to 1.0.16

1.2.2-rapidpro-7.0.4
----------
 * Update weni-rp-apps to 1.0.15
 * Change twilioflex form labels and help text

1.2.1-rapidpro-7.0.4
----------
 * Change refresh templates task schedule to 1h

1.2.0-rapidpro-7.0.4
----------
 * Add ticketer Twilio Flex

1.1.8-rapidpro-7.0.4
----------
 * Added option to exclude channels from claim view when not in the Weni Flows design

1.1.7-rapidpro-7.0.4
----------
 * Added LogRocket in place of Hotjar

1.1.6-rapidpro-7.0.4
----------
 * Add subscribed_apps permission for Instagram Channel
 * Feature to limit recovery password to 5 times in 12 hours.

1.1.5-rapidpro-7.0.4
----------
 * Update weni-rp-apps to 1.0.13
 * Add pages_read_engagement permission for Instagram
 * Fix: back button history behavior 
 * Downgrade elasticsearch version to 7.13.4

1.1.4-rapidpro-7.0.4
----------
 * Update weni-rp-apps to 1.0.12

1.1.3-rapidpro-7.0.4
----------
 * Fix: Use original filename instead uuid at end of path on upload attachment

1.1.2-rapidpro-7.0.4
----------
 * Fix: Branding with privacy url

1.1.1-rapidpro-7.0.4
----------
 * Fix: Kyrgyzstan whatsapp language code

1.1.0-rapidpro-7.0.4
----------
 * Merge instagram channel
 * Lock weni-rp-apps to 1.0.8
 * Feat/back button missing

1.0.7-rapidpro-7.0.4
----------
 * Fix: Gujarati whatsapp language code

1.0.6-rapidpro-7.0.4
----------
 * Add background flow type, location support and title variables in branding info.

1.0.5-rapidpro-7.0.4
----------
 * set NON_ISO6391_LANGUAGES on temba/settings.py.prod

1.0.4-rapidpro-7.0.4
----------
 * fixed CELERY_BROKER_URL

1.0.3-rapidpro-7.0.4
----------
 * DATABASES["readonly"] setting fixed

1.0.2-rapidpro-7.0.4
----------
 * Removed old two-factor authentication

1.0.1-rapidpro-7.0.4
----------
* RapidPro updated to v7.0.4
  * Settings updated on temba/settings.py.prod
    * LOG_TRIM_* variables replaced by RETENTION_PERIODS
    * CELERYBEAT_SCHEDULE updated to CELERY_BEAT_SCHEDULE
* Python updated to 3.9

1.0.1-rapidpro-6.5.15
----------
 * Downgrade psycopg2-binary version to 2.8.6 
 * Removes discontinued elasticapm processor 
 * Add weni-rp-apps to pip dependencies

1.0.0-rapidpro-6.5.15
----------
 * RapidPro v6.5.15
 * Dockerfile with python 3.6 and NodeJS 12
 * Dockerfile with Varnish 6.0 for static files caching
 * Added APM
 * Added log config
 * Allowed 32MB of client body size
 * Added a new env var to enable/disable existing loggers
 * Added weni-rp-apps into INSTALLED_APPS
 * Added Custom layout for use within Weni Connect
 * Enabled authentication from OIDC
 * Enabled CSP configuration
 * Removed Authorization from webhookresult and channellog requests on read
 * Added communication with Weni Connect via PostMessage
