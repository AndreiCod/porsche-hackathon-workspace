# API Documentation
## Endpoint

The endpoint for this API is `http://185.187.169.44:10073/<team_id>`. All requests should be made to this endpoint.
The `team id` will be provided to you by the competition organizers.


## Authentication
The server requires authentication for all requests. All requests should contains a Basic Authentication header with the username and password of the team. These will be provided to you by the competition organizers.

## Supported HTTP Methods 
This endpoint supports the following HTTP methods:

    PUT
    GET
    DELETE
    POST

**Note**: A HTTP response with a status code different than 200 OK indicates an error. The response body will contain a JSON object with the following structure:

    {
        "error": "error message"
    }

## Supported Query Parameters

The following query parameters are supported:

    modelName: The name of the model being uploaded, downloaded or queried.
    listModels: This parameter is used to list all the uploaded models.
    resetModels: This parameter is used to delete all uploaded models.
    uploadResults: This parameter is used to upload the JSON document that contains the results of an inference run on one of the models.
    viewResults: This parameter is used to get the content of all uploaded results documents.
    resetResults: This parameter is used to delete all uploaded results.

### `PUT /<team_id>?modelName=<name_of_model>`

This endpoint is used to upload a model to the server. The modelName query parameter specifies the name of the model being uploaded. The contents of the model are sent in the request body.

Example request:

    PUT /team2?modelName=my_model HTTP/1.1
    Content-Type: application/octet-stream

    <binary_data_of_model>

Example response:

    HTTP/1.1 200 OK

    { "success": true }

### `GET /<team_id>?modelName=<name_of_previously_PUT_model>`

This endpoint is used to download a previously uploaded model from the server. The modelName query parameter specifies the name of the model being downloaded.

Example request:

    GET /team1?modelName=my_model HTTP/1.1

Example response:

    HTTP/1.1 200 OK
    Content-Type: application/octet-stream
    
    <binary_data_of_model>

### `GET /<team_id>?listModels`

This endpoint is used to list all the uploaded models.

Example request:

    GET /team4?listModels HTTP/1.1

Example response:

    HTTP/1.1 200 OK
    Content-Type: application/json

    [
        "my_model",
        "my_second_model"
    ]

### `DELETE /<team_id>?resetModels`

This endpoint is used to delete all uploaded models.

Example request:

    DELETE /team1?resetModels HTTP/1.1

Example response:

    HTTP/1.1 200 OK

    { "success": true }

### `POST /<team_id>?uploadResults`

This endpoint is used to upload the JSON document that contains the results of an inference run on one of the models. The contents of the JSON document are sent in the request body.

Example request:

    POST /team3?uploadResults HTTP/1.1
    Content-Type: application/json
    
    {
        "modelName": "my_model",
        "results": [
            {
                "input": "some input data",
                "output": "some output data"
            },
            {
                "input": "some other input data",
                "output": "some other output data"
            }
        ]
    }

Example response:

    HTTP/1.1 200 OK

    { "success": true }

### `GET /<team_id>?viewResults`

This endpoint is used to get the content of all uploaded results.

Example request:

    GET /team2?viewResults HTTP/1.1

Example response:

    HTTP/1.1 200 OK
    Content-Type: application/json

    [
        {
            "modelName": "my_model1",
            "results": [
                {
                    "input": "some input data",
                    "output": "some output data"
                },
                {
                    "input": "some other input data",
                    "output": "some other output data"
                }
            ]
        },
        {
            "modelName": "my_model2",
            "results": [
                {
                    "input": "some input data",
                    "output": "some output data"
                },
                {
                    "input": "some other input data",
                    "output": "some other output data"
                }
            ]
        }
    ]

### `DELETE /<team_id>?resetResults`

This endpoint is used to delete all uploaded results.

Example request:

    DELETE /team1?resetResults HTTP/1.1

Example response:

    HTTP/1.1 200 OK

    { "success": true }
