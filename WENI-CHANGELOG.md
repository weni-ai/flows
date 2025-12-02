3.46.0
----------
* Implementing optional jwt auth on 2 endpoints
* Endpoint and validation to avoid contact duplication in contacts count

3.45.2
----------
* Fix: package-lock.json issue

3.45.1
----------
* Fix: floweditor lock file issue

3.45.0
----------
* Add locale field to WhatsApp broadcast template documentation
* Change FlowPathCount squash to avoid distinct on query
* Update @weni/flow-editor dependency to version 3.6.4
* Add language field to project update consumer
* Refactor OrgCRUDL view to remove unused sections

3.44.1
----------
* Add jwt auth in internal whatsapp broadcast endpoint
* Endpoint to download contacts according msgs status

3.44.0
----------
* Add Freshchat ticketer integration

3.43.3
----------
* Add migration to optimize broadcast statistics trigger

3.43.2
----------
* Update weni-rp-apps version to 2.10.7

3.43.1
----------
* Remove unnecessary validation on twilio flex 2 claim

3.43.0
----------
* Add twilioflex2 ticketer type and respective claim view

3.42.1
----------
* Add task to update msgs async on channel release
* Add silver in events API
* Add ClaimView to E2 channel
* Improve build

3.42.0
----------
* Increase per-type search limit to 50 and enhance group query matching logic in omnibox search
* Rename project parameter to project_uuid in get_pricing method

3.41.7
----------
* Update weni-rp-apps version to 2.10.6
* Add URN filter in messages endpoint
* Adjust internal endpoint to update name field correctly

3.41.6
----------
* Update Poetry version on Dockerfile to 1.8.5

3.41.5
----------
* Update weni-rp-apps version to 2.10.5
* Fix date error in events endpoint
* Improve Flow Category squash
* Return only queues active
* Endpoint to import flow internally
* Add project_language endpoint

3.41.4
----------
* Update floweditor to 3.6.3

3.41.3
----------
* Fix error in create contact endpoint when verify ninth digit is enabled

3.41.2
----------
* Add endpoint to get events aggregated

3.41.1
----------
* Fix success_rate calculation in BroadcastStatistic

3.41.0
----------
* Add endpoint to list broadcasts with statistics
* Feature/template models new fields
* Add new model fields in whatsapp broadcast creation
* Cost API
* Endpoints to Import Contacts via REST API

3.40.2
----------
* External v2 initialization and listed in settings_common CHANNEL_TYPES

3.40.1
----------
* Add pagination to be used in v2 api
* Add channel filter in internal get message
* Endpoint to upload media

3.40.0
----------
* External v2
* Add trigger to save msg status update in BroadcastStatistics table
* BroadcastStatics new model and Broadcast update
* Endpoint to get flows
* Add possiblity to use IsUserOrg in internal whatsapp broadcast API
* Endpoint to get project data
* Add permission in internal ContactField endpoint

3.39.2
----------
* Add limit and offset in get datalake events endpoint
* Add environ variable in lambda validator url

3.39.1
----------
* Handling the extra ninth digit in WhatsApp URNs for CTWA data fetching

3.39.0
----------
* Send value and currency fields to Meta in purchase conversion events

3.38.1
----------
* Send timestamp and waba id in event to data lake

3.38.0
----------
* Update weni-rp-apps version to 2.10.4
* Enhance conversion event handling to send data to Weni Datalake

3.37.2
----------
* Add isOrgUser permission
* Remove API token logger
* Internal endpoint to get channels

3.37.1
----------
* Update weni-rp-apps version to 2.10.3
* Remove filter to get only contacts with more than one message in get contacts message api

3.37.0
----------
* Endpoint to get contacts with more than one message related

3.36.0
----------
* Add queue field to WhatsappBroadcastWriteSerializer

3.35.10
----------
* Fix: LeadSubmitted event name in Meta Conversion API

3.35.9
----------
* Add logger to see API token and user

3.35.8
----------
* Update floweditor to 3.6.2

3.35.7
----------
* Add internal endpoint to check if contact has open ticket by URN as parameter

3.35.6
----------
* Schedule task squash_flow_category_counts

3.35.5
----------
* Change CAPI endpoint authentication to JWT

3.35.4
----------
* Move squash FlowCategoryCount to a new task 

3.35.3
----------
* Update weni-datalake-sdk version to 0.4.0

3.35.2
----------
* Add environment variable to RedirectMiddleware

3.35.1
----------
* Add config for batch size for squashable models
* Optimization on FLowPathRecentRun prune

3.35.0
----------
* Update weni-rp-apps version to 2.10.2
* Split EDA consumers

3.34.1
----------
* Add protocol param to endpoint request to open ticket

3.34.0
----------
* Add conversion events module with API endpoint for conversion events
* Update weni-ap-apps and weni-datalake-sdk

3.33.0
----------
* Endpoint to get events

3.32.1
----------
* Add filters to flow start logs

3.32.0
----------
* Update weni-rp-apps version to 2.10.0
* Add django-prometheus

3.31.3
----------
* Adjust message template consumer fields to send to datalake
* Bump weni-datalake-sdk version to 0.2.1

3.31.2
----------
* Add router demo number environment variable

3.31.1
----------
* Update weni-rp-apps version to 2.9.4 in poetry.lock and pyproject.toml
* Add MailRoomException in open ticket api

3.31.0
----------
* Feat: remove unused context processors

3.30.0
----------
* Endpoint to get messages with internal authentication

3.29.3
----------
* Update validation in WhatsappBroadcastWriteSerializer to action_type instead of typing_indicator

3.29.2
----------
* Bump weni-rp-apps version to 2.9.3
* Improve validation in WhatsappBroadcastWriteSerializer to require typing_indicator in message payload

3.29.1
----------
* Update floweditor to 3.6.1

3.29.0
----------
* Update weni-rp-apps and add weni-datalake-sdk
* Add consumers to message template

3.28.9
----------
* Remove call to refresh whatsapp products task

3.28.8
----------
* Fix: Convert batch size to int

3.28.7
----------
* Add batch of flow path recent run to environ
* Remove signup form from public index template

3.28.6
----------
* Not save products coming from integrations

3.28.5
----------
* Update floweditor to 3.6.0
* Add instagram feature flag to floweditor

3.28.4
----------
* Update weni-rp-apps version to 2.9.1
* Endpoint to enable/disable channel

3.28.3
----------
* Update floweditor to 3.5.1

3.28.2
----------
* Remove content validation in update template func

3.28.1
----------
* Update channel name length to 128
* Refactor template sync logic and webhook validation
* Add 401 unauthorized template
* Bump weni-rp-apps version to 2.9.0

3.28.0
----------
* fix open ticket endpoint
* Add locale field to template data

3.27.2
----------
* Add validation on update or add urn for contact in edit contact form

3.27.1
----------
* Change get_departments endpoint to return related topics
* Add template validation in contacts templates endpoint

3.27.0
----------
* Internal endpoints to get Departments and Queues
* Change filter to get not null msgs in contacts templates endpoint

3.26.0
----------
* Set verify ninth digit as default in project creation
* Change prune function to flow path recent run
* Add api v2 internal endpoint for open ticket

3.25.0
----------
* Add watchdog mechanism to prevent task overlapping

3.24.4
----------
* Fix task name error
* Update whatsapp flows api permission
* Avoid timeout in flows tasks
* Update postgres version to 15 in CI

3.24.3
----------
* Update weni-rp-apps version to 2.8.16
* Add task to trim all completed flow starts

3.24.2
----------
* Fix error getting data from /accounts in meta
* Add cycle to campaigns_eventfire_id_seq

3.24.1
----------
* Add test and use skip_authentication decorator
* Fix lamba allowed hosts enviroment variable

3.24.0
----------
* Remove error getting next page in products sync
* Endpoint to create ContactField internally
* Add endpoint to add and update field value
* Add endpoint to list project contact fields
* Fix error in sonarcloud

3.23.1
----------
* Add sentry to floweditor
* Update floweditor to 3.5.0

3.23.0
----------
* Add Endpoint to get webchat allowed domains

3.22.0
----------
* Update weni-rp-apps version to 2.8.15
* Endpoint to get contacts internally

3.21.2
----------
* Adjust Internal whatsapp broadcasts tests

3.21.1
----------
* Fix error saving internal whatsapp broadcast

3.21.0
----------
* WhatsappBroadcast to be used internally

3.20.2
----------
* Change template validation in WppBroadcast serializer
* Hide chatgpt key in http logs

3.20.1
----------
* Update weni-rp-apps version to 2.8.14

3.20.0
----------
* Endpoint to assignee user in ticket
* Update weni-rp-apps version to 2.8.13

3.19.1
----------
* Feat: Allow specifying whatsapp broadcast template by name

3.19.0
----------
* Change trim flow session task batch size
* Add task to interrupt flow sessions

3.18.3
----------
* Update floweditor to 3.4.4

3.18.2
----------
* Update floweditor to 3.4.3
* feat: add channel option to whatsapp broadcasts
* feat: update whatsapp broadcasts documentation

3.18.1
----------
* Fix error calling WhatsappBroadcasts in Interface API

3.18.0
----------
* Add new field in Broadcast model to receive whatsapp broadcast
* Add endpoints to whatsapp broadcast
* Add CYCLE in flows_flowstart_contacts_id_seq
* Update weni-rp-apps version to 2.8.12

3.17.0
----------
* Create queue_uuid field in Topic model
* Add queue_uuid in ticketer creation
* Update weni-rp-apps version to 2.8.11

3.16.7
----------
* Increase time sync intents task

3.16.6
----------
* Update keys in Email channel

3.16.5
----------
* Add task to sync whatsapp flows assets
* Fixing telegram lib version
* Fix: Improve contact list response latency by removing reduntant org filtering

3.16.4
----------
* Update floweditor to 3.4.2

3.16.3
----------
* Update floweditor to 3.4.1

3.16.2
----------
* Update floweditor to 3.4.0

3.16.1
----------
* Fix whatsapp flow error when status is draft

3.16.0
----------
* Update floweditor to 3.3.0
* Email channel type
* Update is_active WhatsappFlow when deprecated status
* Schedule whatsapp flows sync

3.15.2
----------
* Update floweditor to 3.2.1

3.15.1
----------
* Fix bug updating whatsapp flow status

3.15.0
----------
* Sync a new whatsapp flow coming from webhook
* Add is_mutable field in flow model
* Update floweditor to 3.2.0

3.14.1
----------
* Fix bug on create contact api
* Add translations to onboard modal

3.14.0
----------
* Create whatsapp_flows model
* Add task to sync whatsapp flows
* Add whatsapp flows endpoint
* Endpoint to whatsapp flows webhook

3.13.8
----------
* Update weni-rp-apps version to 2.8.9
* Update pt_BR and es translations
* Add more translations

3.13.7
----------
* Update floweditor to 3.1.3

3.13.6
----------
* Change msg field size to variable

3.13.5
----------
* Update weni-rp-apps to 2.8.8
* Update translations ES and pt_BR

3.13.4
----------
* Update vonage methods

3.13.3
----------
* Update floweditor to 3.1.1

3.13.2
----------
* Update floweditor to 3.1.0

3.13.1
----------
* Update floweditor to 3.0.2

3.13.0
----------
* Adjust retail consumers

3.12.4
----------
* Add Hotjar

3.12.3
----------
* Update floweditor to 3.0.1

3.12.2
----------
* Remove references with digit 9 in flows

3.12.1
----------
* Hotfix: Resolve error calling elasticsearch

3.12.0
----------
* Fix error on code_check
* Consumer to delete flows objects
* Publisher that will send event that flows were created
* Add consumer to integrate feature template
* Improve query on elasticsearch

3.11.0
----------
* Update floweditor to 3.0.0
* Support new floweditor static file handling
* Add attributes in headers
* Add waba and phone number in billing endpoint
* Change trim flow start task to delete api starts

3.10.10
----------
* Update floweditor to 2.17.1

3.10.9
----------
* Update flow start endpoint to receive query params
* Remove WAC type from update_api_version call
* feat: allow brain

3.10.8
----------
* Add throttle scope to flowstart endpoint

3.10.7
----------
* Change attribute in elastic return
* Update weni-rp-apps to 2.8.7
* Update floweditor to 2.17.0

3.10.6
----------
* Add active_catalog key in update-catalog endpoint
* Convert timeout variable to int

3.10.5
----------
* Update weni-rp-apps version to 2.8.6
* Create index to channel address

3.10.4
----------
* Update weni-rp-apps version to 2.8.5
* Add status choices in TemplateTranslation model

3.10.3
----------
* Change queryset to bring data of 15 days

3.10.2
----------
* Fix: Users endpoint optimization

3.10.1
----------
* Chore: Bump floweditor to 2.16.1

3.10.0
----------
* Chore: Bump floweditor to 2.16.0

3.9.4
----------
* Fix performance in normalize urns
* Change filter in templates endpoint

3.9.3
----------
* Chore: Bump floweditor to 2.15.1

3.9.2
----------
* Add config page for Teams Channel
* Fix: display messages in correct place

3.9.1
----------
* Add template field in Msg model and refact related endpoint
* Update contacts templates endpoint with new template field
* Remove validation in get_features function

3.9.0
----------
* Chore: Bump floweditor to 2.15.0

3.8.5
----------
* Add filter title in product endpoint
* Adjust database variables in Docker Compose to facilitate project execution
* Update before and after to support time in filter template endpoint
* Adds an endpoint that allows you to list projects from channels
* Chore: Bump floweditor to 2.14.0

3.8.4
----------
* Update weni-rp-apps version to 2.8.4

3.8.3
----------
* New field proj_uuid in org model
* Review inactive template and add status in template translation
* Update weni-rp-apps version to 2.8.3

3.8.2
----------
* Prevent template trimming on webhook calls

3.8.1
----------
* Creates endpoint that allows to simulate a flow

3.8.0
----------
* Create consumer to update user permissions

3.7.11
----------
* Chore: Bump floweditor to 2.13.1

3.7.10
----------
* Update weni-rp-apps to 2.8.2
* Call recent activities when flow is archived

3.7.9
----------
* Create internal endpoints that allows to create flow starts and broadcasts

3.7.8
----------
* Update weni-rp-apps to 2.8.1
* Consumer to update brain on
* Endpoint to update template status

3.7.7
----------
* Allow adding classifiers

3.7.6
----------
* Set fixed credits calculation

3.7.5
----------
* Remove credits check from sidebar

3.7.4
----------
* Fix overwritten floweditor version back to 2.13.0

3.7.3
----------
⚠️ Floweditor rolled back to 2.12.0
* Deactivate topup credits tasks
* Add brain_on in create project consumer
* Add brain_on field in Org model

3.7.2
----------
* Chore: Bump floweditor to 2.13.0

3.7.1
----------
* Block manual broadcast for large groups

3.7.0
----------
* Revert "fix error import contact digit 9"
* Change endpoint to update products vtex to be a celery task
* Fix pagination error and urns list empty
* Add publisher in EDA
* Update max length in product model fields
* Update rp-apps version to 2.8.0

3.6.9
----------
* Chore: Bump floweditor to 2.12.0

3.6.8
----------
* Chore: Bump floweditor to 2.11.1

3.6.7
----------
* Fix error import contact digit 9

3.6.6
----------
* Fix performance in contacts elastic endpoint
* Update rp-apps version to 2.7.11

3.6.5
----------
* Hotfix using 3.6.2 version to adjust permission in contact_elastic endpoint

3.6.4
----------
* Change urn return in elastic serializer

3.6.3
----------
* Add condition when not receive parameter
* Update rp-apps version to 2.7.10

3.6.2
----------
* Add filter to contact_templates endpoint
* Endpoint to get contacts elasticsearch

3.6.1
----------
* Endpoint contacts_lean
* Disable template instead deleting

3.6.0
----------
* Chore: Bump floweditor to 2.11.0

3.5.9
----------
* Add endpoint to get contacts templates
* Add user token in facebook tasks
* Add params to filter groups in contacts endpoint

3.5.8
----------
* Chore: Bump floweditor to 2.10.4

3.5.7
----------
* Chore: Bump floweditor to 2.10.3

3.5.6
----------
* Add test for intelligence endpoint
* Add endpoint to update products by integrations
* Update rp-apps from 2.7.8 to 2.7.9

3.5.5
----------
* Chore: Bump floweditor to 2.10.2

3.5.4
----------
* Chore: Bump floweditor to 2.10.1

3.5.3
----------
* Fix error when nexus return 500

3.5.2
----------
* Sync products for only active_catalog
* Create endpoint to get project intelligences
* feat: add knowledge bases endpoint for the floweditor
* feat: update floweditor to 2.10.0

3.5.1
----------
* Update active catalog endpoint

3.5.0
----------
* Add endpoint to receive templates from integrations
* Refact Templates models
* Add endpoints to create catalog
* Update task according to new templates models
* Add trim template method to delete template

3.4.3
----------
* Hotfix: Remove icontains in contacts endpoint

3.4.2
----------
* Update contact URN filter to icontains
* Endpoint to get flows labels
* Add labels parameter in flow endpoint
* Remove empty body in 204 status return
* Add user_email in update project config
* Add translations in template and webhook emails
* Add search parameter in contact endpoint
* Bump floweditor to version 2.9.2 

3.4.1
----------
* Fix error when project is template

3.4.0
----------
* Add contact foreign key in httplog model
* Add log url button in contact history
* Add description in create project and create update project queue
* Dockerfile refactoring and add cache for build
* Bump floweditor version to 2.9.1

3.3.5
----------
* Add filters to Webhook view
* Create endpoint to export webhook and send email
* Filters and export in webhook page
* Update floweditor to 2.9.0

3.3.4
----------
* Change update_api_version method to save channel with update_fields
* Fix duplicated registers in template.json endpoint
* Add cycle attribute in request_logs sequence

3.3.3
----------
* Handle updated geo attachments

3.3.2
----------
* Fix error when not exist an active catalog
* Add catalogs in get_features flow view
* Update Floweditor to 2.8.2

3.3.1
----------
* Update Floweditor to 2.8.1

3.3.0
----------
* Update Floweditor to 2.8.0
* Add models to wpp_product app
* Create task to update catalog and product
* Add endpoint to GET products
* Implement SentenX in flows
* Create endpoint to create/update catalog
* Send product contact history event

3.2.1
----------
* Chore: Update Floweditor to 2.7.1

3.2.0
----------
* Add filters in template.json endpoint
* Fix error in import trigger
* Chore: Update Floweditor to 2.7.0
* Feat: Remove Helphero
* Feat: Control tools guide and modal

3.1.5
----------
* Update FlowEditor to version 2.6.5

3.1.4
----------
* Update FlowEditor to version 2.6.4
* Re-add feedback delayed toggle

3.1.3
----------
* Update FlowEditor to version 2.6.3

3.1.2
----------
* Update FlowEditor to version 2.6.2

3.1.1
----------
* Update FlowEditor to version 2.6.1

3.1.0
----------
* Fix CI
* Update FlowEditor to version 2.6.0
* Remove workspace edit and classifier delete
* Redesign FlowEditor feedback

3.0.1
----------
* Add INTENT_URL in environment and add classifier intention sync
* Update version of weni-rp-apps to 2.7.8

3.0.0
----------
* Add authorizations for users in project creation
* Add get_or_create in project creation
* Remove has issues in flows
* Add handle consumers in event_driven handle
* Create classifier consumer
* Create ticketer consumer

2.2.4
----------
* Update FlowEditor to version 2.5.2

2.2.3
----------
* Update FlowEditor to version 2.5.1

2.2.2
----------
* Update FlowEditor to version 2.5.0

2.2.1
----------
* Update FlowEditor to version 2.4.1

2.2.0
----------
* Update FlowEditor to version 2.4.0

2.1.0
----------
* Create function to add integrations list to export flow
* Create projets and template type consumers
* Add project and template type handlers in event_driven
* Update FlowEditor to version 2.3.0

2.0.7
----------
⚠️ FlowEditor broken due to incorrect build
* Update settings.dev to include weni.internal apps
* Create integration request model
* Update version of weni-rp-apps to 2.7.7
* Create projects and TemplateType model

2.0.6
----------
⚠️ FlowEditor broken due to incorrect build
* Update FlowEditor to version 2.2.0

2.0.5
----------
* Update FlowEditor to version 2.1.0

2.0.4
----------
* Update FlowEditor to version 2.0.3

2.0.3
----------
* Create and Setup event driven app
* Checks if the user user_org exists before fetching triggers 

2.0.2
----------
* Update FlowEditor to version 2.0.2
* Add id prefix on jquery selectors to prevent css conflict with unnnic modals 
* Remove delayed toggle and changed alert color

2.0.1
----------
* Update FlowEditor to version 2.0.1

2.0.0
----------
* Update FlowEditor to version 2.0.0
* Modified trigger flow button text

1.9.11-rapidpro-7.1.27
----------
* Update version of weni-rp-apps to 2.7.6

1.9.10-rapidpro-7.1.27
----------
* Add tests to tickets model
* Add test to instagram
* Add test to legacy/migrations file

1.9.9-rapidpro-7.1.27
----------
* Add tests to Templatetag
* Add test to Teams channel
* Add tests to api app

1.9.8-rapidpro-7.1.27
----------
* Feat: Added new rate again step into floweditor feedback

1.9.7-rapidpro-7.1.27
----------
* Update version of weni-rp-apps to 2.7.5

1.9.6-rapidpro-7.1.27
----------
* Update version of weni-rp-apps to 2.7.4

1.9.5-rapidpro-7.1.27
----------
* Add test to Twilio Flex
* Add test to RocketChat
* Add tests to Weni Chats
* Add tests to ChatGPT
* Add tests to org app
* Add tests for flows views
* Refact externals model to not use ConnectViewBase
* update floweditor to 1.3.1
* Feat: FlowEditor Feedback component
* Remove Org name edit option

1.9.4-rapidpro-7.1.27
----------
* Update version of weni-rp-apps to 2.7.3
* Add mail_base.html and msg_mail_body.haml 

1.9.3-rapidpro-7.1.27
----------
* Update version of weni-rp-apps to 2.7.2
* Remove weni.internal.msgs module import from INSTALLED_APPS

1.9.2-rapidpro-7.1.27
----------
* Update version of weni-rp-apps to 2.7.1
* Add task generate_sent_report_messages
* Change staging build

1.9.1-rapidpro-7.1.27
----------
* Update version of weni-rp-apps to 2.7.0

1.9.0-rapidpro-7.1.27
----------
* Implement tests for context_processors_weni
* Add tests to middleware
* Add tests to omie type
* Update python version in docker file
* External service chatgpt
* remove migration 0091 org plan
* Create action endpoint to chatgpt
* Update version of weni-rp-apps to 2.6.0
* Update FlowEditor to 1.3.0

1.8.10-rapidpro-7.1.27
----------
* Update version of weni-rp-apps to 2.5.0

1.8.9-rapidpro-7.1.27
----------
* Update version of weni-rp-apps to 2.4.4

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
