# Setup 

The project initially was composed using python 3.12.7.
To use this project, first create a venv and install the required packages.

## Environment
```
python3 -m venv venv

source venv/bin/activate

pip install -r requirements.txt
```

## Data
Create a ```/data``` folder in the root and download the ```eval_set.csv```, ```train_cv_set.csv```, and ```train_tune_set.csv``` from https://osf.io/7sc3b/files/osfstorage and move them to ```/data```.

## Scaler Y
If you want to use the reverse scaling to present the user with unscaled voltage values, download the ```scaler_y.pkl``` file from https://osf.io/7sc3b/files/osfstorage and move it to the ```ml_models``` folder.

# Training the Pipeline
Run the ```train_pipeline.ipynb``` to do randomized hyperparameter training and save the best performing pipeline to a ```pipeline.pkl``` file in the ```ml_models``` folder. This will be served by the api.

# Running the api
Run the following command in your terminal from the root of the folder.
```
cd api
python3 main.py
```

# Invoking the model
Navigate to http://127.0.0.1:8000/docs scroll to 'Get Peak Voltages' and click the Test Request button. This will launch a Postman-like API testing client in the browser, allowing you to send customized requests.

Change the body of the request to:
```
{
  "data": [
    {
      "kW_surplus": -0.339195037,
      "kWp": 0.20077307048167847,
      "pvsystems_count": -0.160496378,
      "ta": -0.805279012,
      "gh": -0.629016938,
      "dd": 1.486568899162645,
      "rr": -0.007414627,
      "hour_sin": -0.866025404,
      "hour_cos": 0.5000000000000001,
      "week_sin": 0.12053668025532305,
      "week_cos": 0.992708874,
      "weekday_sin": -0.433883739,
      "weekday_cos": -0.900968868,
      "UW": 0.7945100241432456
    },
    {
      "kW_surplus": 0.8546145945674263,
      "kWp": -0.498652647,
      "pvsystems_count": 0.10038469800213387,
      "ta": 0.7021016657124305,
      "gh": 1.693421641940305,
      "dd": 1.8330900483219936,
      "rr": 0.2927662377874163,
      "hour_sin": 0,
      "hour_cos": -1,
      "week_sin": 0.6631226582407952,
      "week_cos": -0.748510748,
      "weekday_sin": 0.9749279121818236,
      "weekday_cos": -0.222520934,
      "UW": -1.258637361
    }
  ],
  "return_scaled": false
}
```

This will return a PeakVoltageListRepsonse, consisting of a list of two PeakVoltageResponses, with the inital data of the PeakVoltageRequests, including ```U_max``` which is the predicted value in our example.

# Deploying the model
You can deploy the model on a server by simply running (the screen ensures the thread does not stop when the terminal is closed):
```
screen python3 main.py
```

Or build a Docker image on a VM by running:
```
docker build -t my-fastapi-app .
```

The API can then be activated through:
```
docker run -p 8000:8000 my-fastapi-app
```
