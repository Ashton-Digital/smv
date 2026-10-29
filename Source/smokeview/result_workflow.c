#include "options.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include GLUT_H

#include "smokeviewvars.h"
#include "smokeviewdefs.h"
#include "glui_bounds.h"
#include "glui_motion.h"

#define NRESULT_WORKFLOWS 4
#define WORKFLOW_LABEL_LEN 256

enum workflow_type {
  WORKFLOW_VISIBILITY = 0,
  WORKFLOW_TEMPERATURE,
  WORKFLOW_VELOCITY,
  WORKFLOW_PRESSURE
};

typedef struct {
  const char *name;
  char slice_label[WORKFLOW_LABEL_LEN];
  char colorbar_label[WORKFLOW_LABEL_LEN];
  int configured;
  int current_plane;
  int fixed_bounds_valid;
  float fixed_min;
  float fixed_max;
} result_workflow;

typedef struct {
  int group_index;
  int is_vector;
  int idir;
  float position;
} workflow_plane;

/* The visibility label "VIS_C" is a family, not one exact string: FDS's soot
   visibility quantity is sometimes reported as bare "VIS_C" and sometimes with
   a simulation-specific extinction-coefficient/soot-yield suffix such as
   "VIS_C0.9H0.1". SliceLabelMatches() below treats the bare "VIS_C" default
   as a prefix match against either form; any other explicitly configured
   RESULTWORKFLOW label still requires an exact match. */
static result_workflow workflows[NRESULT_WORKFLOWS] = {
  {"visibility",  "VIS_C", "Visibility",  1, -1, 1,   0.0f,  30.0f},
  {"temperature", "temp",          "Temperature", 1, -1, 1,  20.0f, 300.0f},
  {"velocity",    "vel",           "Velocity",    1, -1, 1,   0.0f,  10.0f},
  {"pressure",    "pres",          "Pressure",    1, -1, 1, -70.0f,  70.0f}
};

static const char *default_slice_labels[NRESULT_WORKFLOWS] = {
  "VIS_C", "temp", "vel", "pres"
};

static const char *default_colorbar_labels[NRESULT_WORKFLOWS] = {
  "Visibility", "Temperature", "Velocity", "Pressure"
};

static const float default_fixed_mins[NRESULT_WORKFLOWS] = {0.0f, 20.0f, 0.0f, -70.0f};
static const float default_fixed_maxs[NRESULT_WORKFLOWS] = {30.0f, 300.0f, 10.0f, 70.0f};

static int active_workflow = -1;
static workflow_plane active_plane = {-1, 0, 0, 0.0f};
/* Surfaced on the title HUD (see GetResultWorkflowStatus/ViewportTitle) when a
   shortcut is pressed but produces no visible change, so the failure is not
   silent to a user with no attached console (a desktop launcher or a
   GUI-only remote session never sees the matching stderr warning). */
static char workflow_message[256] = {0};
static int workflow_camera_clip_saved = 0;
static cameradata workflow_camera_saved;
static clipdata workflow_clip_saved;
static int workflow_clip_mode_saved = CLIP_OFF;
static float workflow_zaxis_angles_saved[3];
static int workflow_zoomindex_saved = ZOOMINDEX_ONE;
static int last_view_axis = -1;
static int next_view_stage = 0;

const char *GetResultWorkflowCaptureFeature(void){
  return "SMV_FEATURE_RENDERRESULTS_1 SMV_FEATURE_CAPTURE_PLANES_1";
}

static void HideWorkflowPlane(const workflow_plane *plane);
static void RestoreWorkflowCameraClip(void);
static void SelectWorkflowPlane(int workflow_index, int apply_clip_view, int direction, int requested_plane);
static void ApplyWorkflowClipView(const workflow_plane *plane);

/* ------------------ SetResultWorkflowCaptureTime ------------------------ */

int SetResultWorkflowCaptureTime(float requested_time, float *capture_time){
  float min_time_diff;
  int i, selected_frame = 0;

  UpdateTimes();
  if(global_times == NULL || nglobal_times <= 0)return 0;
  min_time_diff = ABS(global_times[0] - requested_time);
  for(i = 1; i < nglobal_times; i++){
    float time_diff = ABS(global_times[i] - requested_time);

    if(time_diff < min_time_diff){
      min_time_diff = time_diff;
      selected_frame = i;
    }
  }
  SetTimeFrameIndex(selected_frame, PAUSE_TIME);
  script_itime = selected_frame;
  last_time_paused = 1;
  if(capture_time != NULL)*capture_time = global_times[selected_frame];
  return 1;
}

/* ------------------ ReapplyResultWorkflowCaptureClip ------------------------ */

void ReapplyResultWorkflowCaptureClip(void){
  int *clip_enabled;
  float *clip_value;

  if(active_plane.group_index < 0)return;
  switch(active_plane.idir){
    case 1:
      clip_enabled = &clipinfo.clip_xmax;
      clip_value = &clipinfo.xmax;
      break;
    case 2:
      clip_enabled = &clipinfo.clip_ymax;
      clip_value = &clipinfo.ymax;
      break;
    case 3:
      clip_enabled = &clipinfo.clip_zmax;
      clip_value = &clipinfo.zmax;
      break;
    default:
      return;
  }
  clipinfo.clip_xmin = 0;
  clipinfo.clip_xmax = 0;
  clipinfo.clip_ymin = 0;
  clipinfo.clip_ymax = 0;
  clipinfo.clip_zmin = 0;
  clipinfo.clip_zmax = 0;
  clip_mode = CLIP_BLOCKAGES;
  *clip_enabled = 1;
  *clip_value = active_plane.position;
  Clip2Cam(camera_current);
}

/* ------------------ ClearActiveResultWorkflow ------------------------ */

// Hide the selected plane, restore the camera and clipping saved before the
// workflow started and return every workflow to its first step. Configured
// labels and bounds are left alone.
static void ClearActiveResultWorkflow(void){
  int i;

  HideWorkflowPlane(&active_plane);
  RestoreWorkflowCameraClip();
  for(i = 0; i < NRESULT_WORKFLOWS; i++)workflows[i].current_plane = -1;
  active_workflow = -1;
  active_plane.group_index = -1;
}

/* ------------------ BeginResultWorkflowCapture ------------------------ */

void BeginResultWorkflowCapture(void){
  ClearActiveResultWorkflow();
  outline_mode = SCENE_OUTLINE_HIDDEN;
  updatefacelists = 1;
  updatemenu = 1;
}

/* ------------------ GetResultWorkflowStatus ------------------------ */

int GetResultWorkflowStatus(char *label, int label_size){
  result_workflow *workflow;
  float clip_min = 0.0f, clip_max = 0.0f;
  int clip_min_enabled = 0, clip_max_enabled = 0;
  char axis;

  if(label == NULL || label_size <= 0)return 0;
  label[0] = 0;
  if(active_workflow < 0 || active_workflow >= NRESULT_WORKFLOWS || active_plane.group_index < 0){
    if(workflow_message[0] == 0)return 0;
    snprintf(label, (size_t)label_size, "*** %s", workflow_message);
    return 1;
  }

  workflow = workflows + active_workflow;
  axis = (char)('X' + active_plane.idir - 1);
  switch(active_plane.idir){
    case 1:
      clip_min_enabled = clipinfo.clip_xmin;
      clip_max_enabled = clipinfo.clip_xmax;
      clip_min = clipinfo.xmin;
      clip_max = clipinfo.xmax;
      break;
    case 2:
      clip_min_enabled = clipinfo.clip_ymin;
      clip_max_enabled = clipinfo.clip_ymax;
      clip_min = clipinfo.ymin;
      clip_max = clipinfo.ymax;
      break;
    case 3:
      clip_min_enabled = clipinfo.clip_zmin;
      clip_max_enabled = clipinfo.clip_zmax;
      clip_min = clipinfo.zmin;
      clip_max = clipinfo.zmax;
      break;
    default:
      return 0;
  }

  if(workflow_camera_clip_saved == 1 && clip_mode != CLIP_OFF && clip_min_enabled == 1 && clip_max_enabled == 1){
    snprintf(label, (size_t)label_size, "%s (%s) | %c slice: %.3f m | clip: %.3f <= %c <= %.3f m",
             workflow->colorbar_label, workflow->slice_label, axis, active_plane.position,
             clip_min, axis, clip_max);
  }
  else if(workflow_camera_clip_saved == 1 && clip_mode != CLIP_OFF && clip_min_enabled == 1){
    snprintf(label, (size_t)label_size, "%s (%s) | %c slice: %.3f m | clip: %c >= %.3f m",
             workflow->colorbar_label, workflow->slice_label, axis, active_plane.position,
             axis, clip_min);
  }
  else if(workflow_camera_clip_saved == 1 && clip_mode != CLIP_OFF && clip_max_enabled == 1){
    snprintf(label, (size_t)label_size, "%s (%s) | %c slice: %.3f m | clip: %c <= %.3f m",
             workflow->colorbar_label, workflow->slice_label, axis, active_plane.position,
             axis, clip_max);
  }
  else{
    snprintf(label, (size_t)label_size, "%s (%s) | %c slice: %.3f m | clip: off",
             workflow->colorbar_label, workflow->slice_label, axis, active_plane.position);
  }
  return 1;
}

/* ------------------ RestoreWorkflowTime ------------------------ */

static void RestoreWorkflowTime(float selected_time, int selected_time_valid, int selected_stept){
  float min_time_diff;
  int i, selected_frame = 0;

  if(global_times == NULL || nglobal_times <= 0){
    stept = selected_stept;
    return;
  }
  if(selected_time_valid == 0){
    SetTimeFrameIndex(iglobal_times, selected_stept);
    return;
  }
  min_time_diff = ABS(global_times[0] - selected_time);
  for(i = 1; i < nglobal_times; i++){
    float time_diff = ABS(global_times[i] - selected_time);

    if(time_diff < min_time_diff){
      min_time_diff = time_diff;
      selected_frame = i;
    }
  }
  SetTimeFrameIndex(selected_frame, selected_stept);
}

/* ------------------ ResetResultWorkflows ------------------------ */

void ResetResultWorkflows(void){
  int i;

  workflow_message[0] = 0;
  HideWorkflowPlane(&active_plane);
  RestoreWorkflowCameraClip();
  for(i = 0; i < NRESULT_WORKFLOWS; i++){
    strcpy(workflows[i].slice_label, default_slice_labels[i]);
    strcpy(workflows[i].colorbar_label, default_colorbar_labels[i]);
    workflows[i].configured = 1;
    workflows[i].current_plane = -1;
    workflows[i].fixed_bounds_valid = 1;
    workflows[i].fixed_min = default_fixed_mins[i];
    workflows[i].fixed_max = default_fixed_maxs[i];
  }
  active_workflow = -1;
  active_plane.group_index = -1;
  workflow_camera_clip_saved = 0;
  last_view_axis = -1;
  next_view_stage = 0;
}

/* ------------------ GetWorkflowIndex ------------------------ */

static int GetWorkflowIndex(const char *name){
  int i;

  for(i = 0; i < NRESULT_WORKFLOWS; i++){
    if(STRCMP(name, workflows[i].name) == 0)return i;
  }
  return -1;
}

/* ------------------ ConfigureResultWorkflow ------------------------ */

void ConfigureResultWorkflow(const char *name, const char *slice_label, const char *workflow_colorbar_label){
  int index;

  if(name == NULL || slice_label == NULL || workflow_colorbar_label == NULL)return;
  index = GetWorkflowIndex(name);
  if(index < 0){
    fprintf(stderr, "*** Warning: unknown RESULTWORKFLOW name: %s\n", name);
    return;
  }
  if(slice_label[0] == 0 || workflow_colorbar_label[0] == 0){
    fprintf(stderr, "*** Warning: RESULTWORKFLOW %s requires a slice and colorbar label\n", name);
    return;
  }
  strncpy(workflows[index].slice_label, slice_label, WORKFLOW_LABEL_LEN - 1);
  workflows[index].slice_label[WORKFLOW_LABEL_LEN - 1] = 0;
  strncpy(workflows[index].colorbar_label, workflow_colorbar_label, WORKFLOW_LABEL_LEN - 1);
  workflows[index].colorbar_label[WORKFLOW_LABEL_LEN - 1] = 0;
  workflows[index].configured = 1;
  workflows[index].current_plane = -1;
  workflows[index].fixed_bounds_valid = 0;
}

/* ------------------ SliceLabelMatches ------------------------ */

static int SliceLabelMatches(const slicedata *slicei, const char *label){
  if(slicei == NULL || label == NULL)return 0;
  if(STRCMP(slicei->label.shortlabel, label) == 0)return 1;
  if(STRCMP(slicei->label.longlabel, label) == 0)return 1;
  if(STRCMP(label, "VIS_C") == 0){
    if(STRSTR(slicei->label.shortlabel, "VIS_C") == slicei->label.shortlabel)return 1;
    if(STRSTR(slicei->label.longlabel, "VIS_C") == slicei->label.longlabel)return 1;
  }
  return 0;
}

/* ------------------ CompareWorkflowPlanes ------------------------ */

static int CompareWorkflowPlanes(const void *arg1, const void *arg2){
  const workflow_plane *plane1 = (const workflow_plane *)arg1;
  const workflow_plane *plane2 = (const workflow_plane *)arg2;

  if(plane1->idir != plane2->idir)return plane1->idir - plane2->idir;
  if(plane1->position < plane2->position)return -1;
  if(plane1->position > plane2->position)return 1;
  return plane1->group_index - plane2->group_index;
}

/* ------------------ BuildWorkflowPlanes ------------------------ */

static int BuildWorkflowPlanes(const result_workflow *workflow, int is_vector, workflow_plane **planes_ptr){
  workflow_plane *planes;
  int count = 0, i, capacity;

  capacity = is_vector == 1 ? global_scase.slicecoll.nmultivsliceinfo : global_scase.slicecoll.nmultisliceinfo;
  *planes_ptr = NULL;
  if(capacity <= 0)return 0;
  if(NewMemory((void **)&planes, (size_t)capacity * sizeof(workflow_plane)) == 0)return 0;

  for(i = 0; i < capacity; i++){
    slicedata *slicei = NULL;

    if(is_vector == 1){
      multivslicedata *mvslicei = global_scase.slicecoll.multivsliceinfo + i;
      vslicedata *vslicei;

      if(mvslicei->nvslices <= 0)continue;
      vslicei = global_scase.slicecoll.vsliceinfo + mvslicei->ivslices[0];
      if(vslicei->ival < 0)continue;
      slicei = global_scase.slicecoll.sliceinfo + vslicei->ival;
    }
    else{
      multislicedata *mslicei = global_scase.slicecoll.multisliceinfo + i;

      if(mslicei->nslices <= 0)continue;
      slicei = global_scase.slicecoll.sliceinfo + mslicei->islices[0];
    }
    if(slicei->slice3d == 1 || slicei->idir < 1 || slicei->idir > 3)continue;
    if(SliceLabelMatches(slicei, workflow->slice_label) == 0)continue;

    planes[count].group_index = i;
    planes[count].is_vector = is_vector;
    planes[count].idir = slicei->idir;
    planes[count].position = slicei->position_orig;
    count++;
  }
  if(count == 0){
    FREEMEMORY(planes);
    return 0;
  }
  qsort(planes, (size_t)count, sizeof(workflow_plane), CompareWorkflowPlanes);
  *planes_ptr = planes;
  return count;
}

/* ------------------ CaptureNextResultWorkflowPlane ------------------------ */

static int CaptureWorkflowEnabled(const char *name){
  const char *filter = getenv("ASHTON_CAPTURE_QUANTITIES");
  const char *part;
  size_t name_len;

  if(filter == NULL || filter[0] == 0)return 1;
  name_len = strlen(name);
  part = filter;
  while(*part != 0){
    const char *end = strchr(part, ',');
    size_t part_len = end == NULL ? strlen(part) : (size_t)(end - part);

    if(part_len == name_len && strncmp(part, name, name_len) == 0)return 1;
    if(end == NULL)break;
    part = end + 1;
  }
  return 0;
}

static int CapturePlaneEnabled(const workflow_plane *plane){
  const char *filter = getenv("ASHTON_CAPTURE_PLANES");
  const char *part;

  if(filter == NULL || filter[0] == 0)return 1;
  part = filter;
  while(*part != 0){
    char axis = 0;
    float position = 0.0f;
    int consumed = 0;

    if(sscanf(part, " %c = %f %n", &axis, &position, &consumed) >= 2 && consumed > 0 &&
       (part[consumed] == ',' || part[consumed] == 0)){
      if(axis == (char)('x' + plane->idir - 1) && ABS(position - plane->position) <= 0.0005f)return 1;
    }
    part = strchr(part, ',');
    if(part == NULL)break;
    part++;
  }
  return 0;
}

int CaptureNextResultWorkflowPlane(int *workflow_index, int *plane_index,
                                   const char *prefix, char *render_base, int render_base_size){
  int i;

  if(workflow_index == NULL || plane_index == NULL || render_base == NULL || render_base_size <= 0)return 0;
  render_base[0] = 0;
  for(i = MAX(*workflow_index, 0); i < NRESULT_WORKFLOWS; i++){
    workflow_plane *planes = NULL;
    int next_plane = i == *workflow_index ? *plane_index + 1 : 0;
    int nplanes;

    if(CaptureWorkflowEnabled(workflows[i].name) == 0){
      *plane_index = -1;
      continue;
    }
    nplanes = BuildWorkflowPlanes(workflows + i, 0, &planes);

    while(next_plane >= 0 && next_plane < nplanes && CapturePlaneEnabled(planes + next_plane) == 0)next_plane++;
    if(next_plane >= 0 && next_plane < nplanes){
      char position[64];
      int j;

      snprintf(position, sizeof(position), "%.3f", planes[next_plane].position);
      for(j = 0; position[j] != 0; j++){
        if(position[j] == '-')position[j] = 'm';
        if(position[j] == '.')position[j] = 'p';
      }
      snprintf(render_base, (size_t)render_base_size, "%s%s%s_%c_%03i_%s",
               prefix == NULL ? "" : prefix,
               prefix == NULL || prefix[0] == 0 ? "" : "_",
               workflows[i].name, (char)('x' + planes[next_plane].idir - 1),
               next_plane + 1, position);
      FREEMEMORY(planes);
      SelectWorkflowPlane(i, 1, 1, next_plane);
      *workflow_index = i;
      *plane_index = next_plane;
      return active_workflow == i && active_plane.group_index >= 0;
    }
    FREEMEMORY(planes);
    *plane_index = -1;
  }
  return 0;
}

/* ------------------ HideWorkflowPlane ------------------------ */

static void HideWorkflowPlane(const workflow_plane *plane){
  int i;

  if(plane == NULL || plane->group_index < 0)return;
  if(plane->is_vector == 1){
    multivslicedata *mvslicei = global_scase.slicecoll.multivsliceinfo + plane->group_index;
    for(i = 0; i < mvslicei->nvslices; i++){
      vslicedata *vslicei = global_scase.slicecoll.vsliceinfo + mvslicei->ivslices[i];
      vslicei->display = 0;
    }
  }
  else{
    multislicedata *mslicei = global_scase.slicecoll.multisliceinfo + plane->group_index;
    for(i = 0; i < mslicei->nslices; i++){
      slicedata *slicei = global_scase.slicecoll.sliceinfo + mslicei->islices[i];
      slicei->display = 0;
    }
  }
  updatemenu = 1;
  GLUTPOSTREDISPLAY;
}

/* ------------------ LoadScalarWorkflowPlane ------------------------ */

static void LoadScalarWorkflowPlane(const workflow_plane *plane){
  multislicedata *mslicei = global_scase.slicecoll.multisliceinfo + plane->group_index;
  int last_unloaded = -1, i;

  for(i = mslicei->nslices - 1; i >= 0; i--){
    slicedata *slicei = global_scase.slicecoll.sliceinfo + mslicei->islices[i];
    if(slicei->skipdup == 0 && slicei->loaded == 0){
      last_unloaded = mslicei->islices[i];
      break;
    }
  }
  for(i = 0; i < mslicei->nslices; i++){
    int slice_index = mslicei->islices[i];
    slicedata *slicei = global_scase.slicecoll.sliceinfo + slice_index;

    if(slicei->skipdup == 1)continue;
    if(slicei->loaded == 0){
      int color_flag = slice_index == last_unloaded ? SET_SLICECOLOR : DEFER_SLICECOLOR;
      slicei->finalize = slice_index == last_unloaded;
      LoadSlicei(color_flag, slice_index, ALL_FRAMES, NULL);
    }
    slicei->display = 1;
  }
  if(mslicei->nslices > 0){
    slicedata *slicei = global_scase.slicecoll.sliceinfo + mslicei->islices[0];

    // ReadSlice selects the slice type only while loading a new file.  Restore
    // it explicitly when revisiting an already-loaded workflow, otherwise the
    // renderer continues filtering for the previously selected quantity.
    slicefile_labelindex = slicei->slicefile_labelindex;
  }
  SetLoadedSliceBounds(mslicei->islices, mslicei->nslices);
  UpdateSliceFilenum();
  plotstate = GetPlotState(DYNAMIC_PLOTS);
  UpdateShow();
}

/* ------------------ LoadVectorWorkflowPlane ------------------------ */

static void LoadVectorWorkflowPlane(const workflow_plane *plane){
  multivslicedata *mvslicei = global_scase.slicecoll.multivsliceinfo + plane->group_index;
  int *slice_list = NULL;
  int nslices = 0, i;

  if(mvslicei->nvslices > 0)NewMemory((void **)&slice_list, (size_t)mvslicei->nvslices * sizeof(int));
  for(i = 0; i < mvslicei->nvslices; i++){
    int vslice_index = mvslicei->ivslices[i];
    vslicedata *vslicei = global_scase.slicecoll.vsliceinfo + vslice_index;

    if(vslicei->skip == 1)continue;
    if(vslicei->loaded == 0)LoadVSliceMenu2(vslice_index);
    vslicei->display = 1;
    if(slice_list != NULL && vslicei->ival >= 0)slice_list[nslices++] = vslicei->ival;
  }
  if(nslices > 0){
    slicedata *slicei = global_scase.slicecoll.sliceinfo + slice_list[0];

    slicefile_labelindex = slicei->slicefile_labelindex;
    SetLoadedSliceBounds(slice_list, nslices);
    UpdateSliceFilenum();
    plotstate = GetPlotState(DYNAMIC_PLOTS);
    UpdateShow();
  }
  FREEMEMORY(slice_list);
}

/* ------------------ ApplyWorkflowColorbar ------------------------ */

static void ApplyWorkflowColorbar(const result_workflow *workflow){
  colorbardata *colorbar;

  colorbar = GetColorbar(&colorbars, workflow->colorbar_label);
  if(colorbar == NULL){
    fprintf(stderr, "*** Warning: workflow %s colorbar not found: %s\n", workflow->name, workflow->colorbar_label);
    return;
  }
  ColorbarMenu((int)(colorbar - colorbars.colorbarinfo));
}

/* ------------------ ApplyWorkflowBounds ------------------------ */

static void ApplyWorkflowBounds(result_workflow *workflow, const workflow_plane *plane){
  float valmin = 1.0f, valmax = 0.0f, configured_min = 0.0f, configured_max = 0.0f;
  int set_valmin = BOUND_LOADED_MIN, set_valmax = BOUND_LOADED_MAX;
  const char *bounds_label = workflow->slice_label;
  int i;

  if(plane->is_vector == 1){
    multivslicedata *mvslicei = global_scase.slicecoll.multivsliceinfo + plane->group_index;
    if(mvslicei->nvslices > 0){
      vslicedata *vslicei = global_scase.slicecoll.vsliceinfo + mvslicei->ivslices[0];
      if(vslicei->ival >= 0)bounds_label = global_scase.slicecoll.sliceinfo[vslicei->ival].label.shortlabel;
    }
  }
  else{
    multislicedata *mslicei = global_scase.slicecoll.multisliceinfo + plane->group_index;
    if(mslicei->nslices > 0)bounds_label = global_scase.slicecoll.sliceinfo[mslicei->islices[0]].label.shortlabel;
  }

  if(workflow->fixed_bounds_valid == 1){
    SetSliceMin(BOUND_SET_MIN, workflow->fixed_min, (char *)bounds_label);
    SetSliceMax(BOUND_SET_MAX, workflow->fixed_max, (char *)bounds_label);
    return;
  }
  GLUIGetMinMax(BOUND_SLICE, (char *)bounds_label,
                &set_valmin, &configured_min, &set_valmax, &configured_max);
  if(set_valmin == BOUND_SET_MIN && set_valmax == BOUND_SET_MAX){
    workflow->fixed_bounds_valid = 1;
    workflow->fixed_min = configured_min;
    workflow->fixed_max = configured_max;
    SetSliceMin(BOUND_SET_MIN, workflow->fixed_min, (char *)bounds_label);
    SetSliceMax(BOUND_SET_MAX, workflow->fixed_max, (char *)bounds_label);
    return;
  }

  if(plane->is_vector == 1){
    multivslicedata *mvslicei = global_scase.slicecoll.multivsliceinfo + plane->group_index;

    for(i = 0; i < mvslicei->nvslices; i++){
      vslicedata *vslicei = global_scase.slicecoll.vsliceinfo + mvslicei->ivslices[i];
      slicedata *slicei;

      if(vslicei->ival < 0)continue;
      slicei = global_scase.slicecoll.sliceinfo + vslicei->ival;
      if(valmin > valmax){
        valmin = slicei->valmin_slice;
        valmax = slicei->valmax_slice;
      }
      else{
        valmin = MIN(valmin, slicei->valmin_slice);
        valmax = MAX(valmax, slicei->valmax_slice);
      }
    }
  }
  else{
    multislicedata *mslicei = global_scase.slicecoll.multisliceinfo + plane->group_index;

    for(i = 0; i < mslicei->nslices; i++){
      slicedata *slicei = global_scase.slicecoll.sliceinfo + mslicei->islices[i];

      if(slicei->skipdup == 1)continue;
      if(valmin > valmax){
        valmin = slicei->valmin_slice;
        valmax = slicei->valmax_slice;
      }
      else{
        valmin = MIN(valmin, slicei->valmin_slice);
        valmax = MAX(valmax, slicei->valmax_slice);
      }
    }
  }
  if(valmin <= valmax){
    fprintf(stderr, "*** Warning: workflow %s has no fixed V2_SLICE bounds; using loaded bounds\n", workflow->name);
    SetSliceMin(BOUND_LOADED_MIN, valmin, (char *)bounds_label);
    SetSliceMax(BOUND_LOADED_MAX, valmax, (char *)bounds_label);
  }
}

/* ------------------ CacheWorkflowBounds ------------------------ */

static void CacheWorkflowBounds(result_workflow *workflow){
  float configured_min = 0.0f, configured_max = 0.0f;
  int set_valmin = BOUND_LOADED_MIN, set_valmax = BOUND_LOADED_MAX;

  if(workflow->fixed_bounds_valid == 1)return;
  GLUIGetMinMax(BOUND_SLICE, workflow->slice_label,
                &set_valmin, &configured_min, &set_valmax, &configured_max);
  if(set_valmin != BOUND_SET_MIN || set_valmax != BOUND_SET_MAX)return;
  workflow->fixed_bounds_valid = 1;
  workflow->fixed_min = configured_min;
  workflow->fixed_max = configured_max;
}

/* ------------------ CacheAllWorkflowBounds ------------------------ */

static void CacheAllWorkflowBounds(void){
  int i;

  for(i = 0; i < NRESULT_WORKFLOWS; i++){
    if(workflows[i].configured == 1)CacheWorkflowBounds(workflows + i);
  }
}

/* ------------------ SaveWorkflowCameraClip ------------------------ */

static void SaveWorkflowCameraClip(void){
  if(workflow_camera_clip_saved == 1)return;
  memcpy(&workflow_camera_saved, camera_current, sizeof(cameradata));
  memcpy(&workflow_clip_saved, &clipinfo, sizeof(clipdata));
  memcpy(workflow_zaxis_angles_saved, zaxis_angles, sizeof(workflow_zaxis_angles_saved));
  workflow_clip_mode_saved = clip_mode;
  workflow_zoomindex_saved = zoomindex;
  workflow_camera_clip_saved = 1;
}

/* ------------------ RestoreWorkflowCameraClip ------------------------ */

static void RestoreWorkflowCameraClip(void){
  if(workflow_camera_clip_saved == 0)return;
  memcpy(&clipinfo, &workflow_clip_saved, sizeof(clipdata));
  clip_mode = workflow_clip_mode_saved;
  CopyCamera(camera_current, &workflow_camera_saved);
  memcpy(zaxis_angles, workflow_zaxis_angles_saved, sizeof(workflow_zaxis_angles_saved));
  zoomindex = workflow_zoomindex_saved;
  if(rotation_type == ROTATION_3AXIS)Camera2Quat(camera_current, quat_general, quat_rotation);
  GLUIUpdateClip();
  updatefacelists = 1;
  global_scase.updatefaces = 1;
  workflow_camera_clip_saved = 0;
}

/* ------------------ SetFittedAxisView ------------------------ */

static void SetFittedAxisView(int view){
  int fit_option;

  switch(view){
    case MENU_VIEW_XMIN:
    case MENU_VIEW_XMAX:
      fit_option = 1;
      break;
    case MENU_VIEW_YMIN:
    case MENU_VIEW_YMAX:
      fit_option = 2;
      break;
    case MENU_VIEW_ZMIN:
    case MENU_VIEW_ZMAX:
      fit_option = 3;
      break;
    default:
      return;
  }

  // Axis-view helpers restore the saved exterior camera in orthographic mode.
  // Reinitialize the camera so saved pan, centre and zoom values cannot affect
  // result review views, then fit the visible model dimensions for this axis.
  if(projection_type == PROJECTION_ORTHOGRAPHIC){
    float fitted_near;
    int use_geom_factors_save = use_geom_factors;

    SetCameraView(camera_current, view);
    // Review images must contain the complete FDS domain. Geometry-derived
    // extents can be asymmetric or omit empty parts of the domain.
    use_geom_factors = 0;
    InitCamera(camera_current, "current");
    UpdateCameraYpos(camera_current, fit_option);
    use_geom_factors = use_geom_factors_save;
    // UpdateCameraYpos stores the size-preserving camera distance separately.
    // Using its perspective eye position here can put the orthographic near
    // plane close to zero, particularly for Z views, causing extreme zoom.
    camera_current->eye[1] = camera_current->isometric_y;
    // Leave room for labels and the time bar around a nominal zoom-1 view.
    fitted_near = -camera_current->eye[1] - 1.0f;
    camera_current->eye[1] = -1.25f * fitted_near - 1.0f;
  }
  else{
    InitCamera(camera_current, "current");
    SetCameraView(camera_current, view);
  }
  if(rotation_type == ROTATION_3AXIS){
    camera_current->quat_defined = 0;
    Camera2Quat(camera_current, quat_general, quat_rotation);
  }
  camera_current->zoom = 1.0f;
  zoom = 1.0f;
  zoomindex = ZOOMINDEX_ONE;
  GLUIUpdateZoom();
}

/* ------------------ RefitActiveResultWorkflowView ------------------------ */

int RefitActiveResultWorkflowView(void){
  clipdata clip_saved;
  int clip_mode_saved, view;

  if(active_workflow < 0 || active_plane.group_index < 0)return 0;
  switch(active_plane.idir){
    case 1:
      view = MENU_VIEW_XMAX;
      break;
    case 2:
      view = MENU_VIEW_YMAX;
      break;
    case 3:
      view = MENU_VIEW_ZMAX;
      break;
    default:
      return 0;
  }

  // Projection changes use a generic Y-axis camera fit. Reapply the active
  // workflow's axis fit, while retaining its clipping side and coordinate.
  memcpy(&clip_saved, &clipinfo, sizeof(clipdata));
  clip_mode_saved = clip_mode;
  SetFittedAxisView(view);
  memcpy(&clipinfo, &clip_saved, sizeof(clipdata));
  clip_mode = clip_mode_saved;
  Clip2Cam(camera_current);
  GLUIUpdateClip();
  updatefacelists = 1;
  global_scase.updatefaces = 1;
  GLUTPOSTREDISPLAY;
  return 1;
}

/* ------------------ ApplyWorkflowClipView ------------------------ */

static void ApplyWorkflowClipView(const workflow_plane *plane){
  int view;
  int *clip_enabled;
  float *clip_value;

  SaveWorkflowCameraClip();
  switch(plane->idir){
    case 1:
      clip_enabled = &clipinfo.clip_xmax;
      clip_value = &clipinfo.xmax;
      view = MENU_VIEW_XMAX;
      break;
    case 2:
      clip_enabled = &clipinfo.clip_ymax;
      clip_value = &clipinfo.ymax;
      view = MENU_VIEW_YMAX;
      break;
    case 3:
      clip_enabled = &clipinfo.clip_zmax;
      clip_value = &clipinfo.zmax;
      view = MENU_VIEW_ZMAX;
      break;
    default:
      return;
  }

  // Orthographic view changes restore the exterior camera, including its clip state.
  SetFittedAxisView(view);
  clipinfo.clip_xmin = 0;
  clipinfo.clip_xmax = 0;
  clipinfo.clip_ymin = 0;
  clipinfo.clip_ymax = 0;
  clipinfo.clip_zmin = 0;
  clipinfo.clip_zmax = 0;
  clip_mode = CLIP_BLOCKAGES;
  *clip_enabled = 1;
  *clip_value = plane->position;
  Clip2Cam(camera_current);
  GLUIUpdateClip();
  PRINTF("Review clipping: %c <= %.3f\n", 'X' + plane->idir - 1, plane->position);
  updatefacelists = 1;
  global_scase.updatefaces = 1;
  GLUTPOSTREDISPLAY;
}

/* ------------------ FlipWorkflowClipSide ------------------------ */

static int FlipWorkflowClipSide(void){
  float *clip_min, *clip_max, clip_value;
  int *clip_min_enabled, *clip_max_enabled;
  char axis;

  if(active_workflow < 0 || active_plane.group_index < 0)return 0;
  axis = (char)('X' + active_plane.idir - 1);
  switch(active_plane.idir){
    case 1:
      clip_min_enabled = &clipinfo.clip_xmin;
      clip_max_enabled = &clipinfo.clip_xmax;
      clip_min = &clipinfo.xmin;
      clip_max = &clipinfo.xmax;
      break;
    case 2:
      clip_min_enabled = &clipinfo.clip_ymin;
      clip_max_enabled = &clipinfo.clip_ymax;
      clip_min = &clipinfo.ymin;
      clip_max = &clipinfo.ymax;
      break;
    case 3:
      clip_min_enabled = &clipinfo.clip_zmin;
      clip_max_enabled = &clipinfo.clip_zmax;
      clip_min = &clipinfo.zmin;
      clip_max = &clipinfo.zmax;
      break;
    default:
      return 1;
  }

  if(workflow_camera_clip_saved == 0 || clip_mode == CLIP_OFF)return 1;
  if(*clip_max_enabled == 1){
    clip_value = *clip_max;
    *clip_max_enabled = 0;
    *clip_min_enabled = 1;
    *clip_min = clip_value;
    PRINTF("Review clipping: %c >= %.3f\n", axis, clip_value);
  }
  else if(*clip_min_enabled == 1){
    clip_value = *clip_min;
    *clip_min_enabled = 0;
    *clip_max_enabled = 1;
    *clip_max = clip_value;
    PRINTF("Review clipping: %c <= %.3f\n", axis, clip_value);
  }
  else{
    return 1;
  }

  Clip2Cam(camera_current);
  GLUIUpdateClip();
  updatefacelists = 1;
  global_scase.updatefaces = 1;
  GLUTPOSTREDISPLAY;
  return 1;
}

/* ------------------ UnloadAllResultData ------------------------ */

static int UnloadAllResultData(void){
  // Clear the workflow first so the pre-workflow camera and clipping are back
  // before the data they were fitted to is unloaded.
  ClearActiveResultWorkflow();
  LoadUnloadMenu(UNLOADALL);
  return 1;
}

/* ------------------ ReportWorkflowMessage ------------------------ */

/* Surfaces a workflow failure once, on the title HUD (see
   workflow_message/GetResultWorkflowStatus above). Repeating the same failure
   -- which happens naturally when a user presses or holds an unresponsive
   shortcut -- is a no-op past the first occurrence, rather than repeating a
   redisplay on every single keypress. Deliberately does not write to stderr:
   that write was a synchronous, possibly slow flush (e.g. over a networked
   home directory or a remote-desktop session), and repeating it on every
   held/repeated keypress was the actual cause of shortcuts feeling sluggish. */
static void ReportWorkflowMessage(const char *message){
  if(STRCMP(workflow_message, message) == 0)return;
  strncpy(workflow_message, message, sizeof(workflow_message) - 1);
  workflow_message[sizeof(workflow_message) - 1] = 0;
  GLUTPOSTREDISPLAY;
}

/* ------------------ SelectWorkflowPlane ------------------------ */

static void SelectWorkflowPlane(int workflow_index, int apply_clip_view, int direction, int requested_plane){
  result_workflow *workflow = workflows + workflow_index;
  workflow_plane *planes = NULL;
  float selected_time = 0.0f;
  int selected_time_valid = 0;
  int selected_stept = stept;
  int plane_index;
  int is_vector = 0;
  int nplanes;

  if(global_times != NULL && nglobal_times > 0){
    selected_time = GetTime();
    selected_time_valid = 1;
  }

  if(workflow->configured == 0){
    char message[256];

    snprintf(message, sizeof(message), "RESULTWORKFLOW %s is not configured", workflow->name);
    ReportWorkflowMessage(message);
    return;
  }
  // Loading a slice may replace fixed INI bounds with its loaded-data range.
  // Preserve the configured workflow range before the first file is loaded.
  CacheAllWorkflowBounds();
  nplanes = BuildWorkflowPlanes(workflow, is_vector, &planes);
  if(nplanes == 0){
    char message[WORKFLOW_LABEL_LEN + 64];

    snprintf(message, sizeof(message), "no %s slices match label \"%s\" in this case",
             workflow->name, workflow->slice_label);
    ReportWorkflowMessage(message);
    return;
  }

  workflow_message[0] = 0;
  HideWorkflowPlane(&active_plane);
  if(apply_clip_view == 0)RestoreWorkflowCameraClip();
  if(requested_plane >= 0){
    plane_index = requested_plane;
  }
  else if(active_workflow == workflow_index){
    plane_index = workflow->current_plane + direction;
  }
  else{
    plane_index = direction > 0 ? 0 : nplanes - 1;
  }

  if(plane_index < 0 || plane_index >= nplanes){
    workflow->current_plane = -1;
    active_workflow = -1;
    active_plane.group_index = -1;
    RestoreWorkflowCameraClip();
    PRINTF("Review workflow %s: off\n", workflow->name);
    FREEMEMORY(planes);
    return;
  }

  workflow->current_plane = plane_index;
  active_plane = planes[plane_index];
  active_workflow = workflow_index;
  PRINTF("Review workflow %s: %c slice at %.3f (%i of %i)\n",
         workflow->name, 'X' + active_plane.idir - 1, active_plane.position,
         plane_index + 1, nplanes);
  if(active_plane.is_vector == 1)LoadVectorWorkflowPlane(&active_plane);
  else LoadScalarWorkflowPlane(&active_plane);
  ApplyWorkflowColorbar(workflow);
  RestoreWorkflowTime(selected_time, selected_time_valid, selected_stept);
  ApplyWorkflowBounds(workflow, &active_plane);
  UpdateSliceBounds2();
  UpdateRGBColors(colorbar_select_index);
  if(apply_clip_view == 1)ApplyWorkflowClipView(&active_plane);
  GLUTPOSTREDISPLAY;
  FREEMEMORY(planes);
}

/* ------------------ CycleAxisView ------------------------ */

static void CycleAxisView(int axis){
  static const int views[3][2] = {
    {MENU_VIEW_XMIN, MENU_VIEW_XMAX},
    {MENU_VIEW_YMIN, MENU_VIEW_YMAX},
    {MENU_VIEW_ZMIN, MENU_VIEW_ZMAX}
  };

  RestoreWorkflowCameraClip();
  if(last_view_axis != axis){
    last_view_axis = axis;
    next_view_stage = 0;
  }
  if(next_view_stage < 2)SetFittedAxisView(views[axis][next_view_stage]);
  else SetViewPoint(RESTORE_EXTERIOR_VIEW);
  next_view_stage = (next_view_stage + 1) % 3;
  GLUTPOSTREDISPLAY;
}

/* ------------------ HandleResultWorkflowShortcut ------------------------ */

int HandleResultWorkflowShortcut(unsigned char key, int modifiers){
  int apply_clip_view;
  int direction;
  unsigned char lower_key;

  if((modifiers & GLUT_ACTIVE_CTRL) == 0 || (modifiers & GLUT_ACTIVE_ALT) != 0)return 0;
  lower_key = key;
  if(lower_key >= 1 && lower_key <= 26)lower_key = (unsigned char)('a' + lower_key - 1);
  if(lower_key >= 'A' && lower_key <= 'Z')lower_key = (unsigned char)(lower_key - 'A' + 'a');
  apply_clip_view = 1;
  direction = (modifiers & GLUT_ACTIVE_SHIFT) != 0 ? -1 : 1;

  switch(lower_key){
    case 'x':
      if((modifiers & GLUT_ACTIVE_SHIFT) != 0)return 0;
      CycleAxisView(0);
      return 1;
    case 'y':
      if((modifiers & GLUT_ACTIVE_SHIFT) != 0)return 0;
      CycleAxisView(1);
      return 1;
    case 'z':
      if((modifiers & GLUT_ACTIVE_SHIFT) != 0)return 0;
      CycleAxisView(2);
      return 1;
    case 'i':
    case 'l':
      /* 'l' is a collision-free backup for visibility: Ctrl+I shares its
         key code with TAB, which some window managers and remote-desktop
         clients intercept before Smokeview ever sees it. */
      SelectWorkflowPlane(WORKFLOW_VISIBILITY, apply_clip_view, direction, -1);
      return 1;
    case 't':
      SelectWorkflowPlane(WORKFLOW_TEMPERATURE, apply_clip_view, direction, -1);
      return 1;
    case 'v':
      SelectWorkflowPlane(WORKFLOW_VELOCITY, apply_clip_view, direction, -1);
      return 1;
    case 'p':
      SelectWorkflowPlane(WORKFLOW_PRESSURE, apply_clip_view, direction, -1);
      return 1;
    case 'm':
      return FlipWorkflowClipSide();
    case 'u':
      if((modifiers & GLUT_ACTIVE_SHIFT) != 0)return 0;
      return UnloadAllResultData();
    default:
      return 0;
  }
}
